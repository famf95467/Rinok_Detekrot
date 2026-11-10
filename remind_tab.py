# -*- coding: utf-8 -*-
"""Напоминания о подтверждении заказа во вкладке «Аккаунт» (версия 1).
Нужны рядом account_tab.py, chat_tab.py, funpay_manage.py.

Порядок: «Найти заказы» (один запрос страницы /orders/trade, ничего не отправляется) -> вы видите список
и снимаете галочки -> «Отправить выбранным» (после подтверждения; по одному покупателю, с паузами).
Берутся заказы со статусом «Оплачен» старше 24 часов. Одному покупателю уходит ОДНО сообщение за раз
(если у него несколько таких заказов, номера перечисляются в одном тексте).
Не пишем покупателю, если ему напоминание уходило меньше 24 часов назад. На один заказ не больше 3 напоминаний.
За один раз не больше 30 покупателей. Журнал: reminders_log.json (только ID покупателя, номера заказов и время,
текст сообщений не хранится).
Страница /orders/trade и её разметка написаны по памяти и НЕ проверены на живом сайте. Если дату или покупателя
не удалось разобрать, заказ пропускается и показывается в счётчиках, а не угадывается."""
import datetime, json, os, re
from bs4 import BeautifulSoup
import funpay_manage as fm
import account_tab as acc
import chat_tab as chat

LOGFILE = os.path.join(fm.HERE, 'reminders_log.json')
MIN_AGE_H = 24
GAP_H = 24
MAX_PER_ORDER = 3
MAX_PER_RUN = 30
MAX_TEXT = 1000
R = {'groups': {}}
MONTHS = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
          'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}


def read_log():
    try:
        with open(LOGFILE, encoding='utf-8') as f:
            d = json.load(f)
        return {'buyers': dict(d.get('buyers', {})), 'orders': dict(d.get('orders', {}))}
    except (OSError, ValueError, AttributeError):
        return {'buyers': {}, 'orders': {}}


def write_log(d):
    tmp = LOGFILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, LOGFILE)


def age_hours(left, absd, now):
    """Возраст заказа в часах: сначала «N часов назад», потом дата «10 ноября, 21:18». Не разобрали: None."""
    s = (left or '').strip().lower()
    m = re.search(r'(\d+)?\s*(минут|мин\b|час|д(?:ень|ня|ней)|недел|месяц)', s)
    if m and 'назад' in s:
        n = int(m.group(1)) if m.group(1) else 1
        u = m.group(2)
        if u.startswith('мин'):
            return n / 60
        if u.startswith('час'):
            return float(n)
        if u.startswith('д'):
            return n * 24.0
        return n * (168.0 if u.startswith('недел') else 720.0)
    s = (absd or '').strip().lower()
    m = re.match(r'(сегодня|вчера),?\s*(\d{1,2}):(\d{2})', s)
    try:
        if m:
            d = now.date() - datetime.timedelta(days=1 if m.group(1) == 'вчера' else 0)
            t = datetime.datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3)))
        else:
            m = re.match(r'(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?,?\s*(\d{1,2}):(\d{2})', s)
            if not m or m.group(2) not in MONTHS:
                return None
            y = int(m.group(3)) if m.group(3) else now.year
            t = datetime.datetime(y, MONTHS[m.group(2)], int(m.group(1)), int(m.group(4)), int(m.group(5)))
            if t > now and not m.group(3):
                t = t.replace(year=y - 1)
    except ValueError:
        return None
    return max(0.0, (now - t).total_seconds() / 3600)


def _buyer(it):
    box = it.select_one('.media-user-name')
    if not box:
        return None, ''
    name = box.get_text(' ', strip=True)
    for e in [box] + box.find_all(True):
        for attr in ('href', 'data-href'):
            m = re.search(r'/users/(\d+)', e.get(attr, '') or '')
            if m:
                return m.group(1), name
    return None, name


def scan():
    _, _, html = fm.request('/orders/trade', acc.S['key'])
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('a.tc-item')
    if not items or not any(it.select_one('.tc-status') for it in items):
        seen = set()
        for e in soup.find_all(True):
            for c in e.get('class', []):
                if c.startswith(('tc-', 'order')):
                    seen.add(c)
        raise fm.Stop('Заказы на странице /orders/trade не найдены: разметка другая или заказов нет. '
                      'Классы на странице (без содержимого заказов): ' + (', '.join(sorted(seen)[:40]) or '(нет)')
                      + '. Пришлите мне этот список.')
    now = datetime.datetime.now()
    log = read_log()
    cnt = {'on_page': len(items), 'paid': 0, 'young': 0, 'no_date': 0, 'no_buyer': 0}
    by = {}
    for it in items:
        st = it.select_one('.tc-status')
        if not st or st.get_text(strip=True).casefold() != 'оплачен':
            continue
        cnt['paid'] += 1
        m = re.search(r'/orders/([A-Za-z0-9]+)', it.get('href', ''))
        oid = m.group(1) if m else ''
        left, absd = it.select_one('.tc-date-left'), it.select_one('.tc-date-time')
        age = age_hours(left.get_text(' ', strip=True) if left else '', absd.get_text(' ', strip=True) if absd else '', now)
        uid, name = _buyer(it)
        if not oid or not uid:
            cnt['no_buyer'] += 1
            continue
        if age is None:
            cnt['no_date'] += 1
            continue
        if age < MIN_AGE_H:
            cnt['young'] += 1
            continue
        t = it.select_one('.order-desc div')
        g = by.setdefault(uid, {'buyer': uid, 'name': name, 'orders': []})
        g['orders'].append({'id': oid, 'age': round(age, 1), 'title': t.get_text(' ', strip=True)[:80] if t else '',
                            'sent': int(log['orders'].get(oid, 0))})
    groups, R['groups'], n_ok = [], {}, 0
    for g in sorted(by.values(), key=lambda x: -max(o['age'] for o in x['orders'])):
        last = log['buyers'].get(g['buyer'])
        left_orders = [o for o in g['orders'] if o['sent'] < MAX_PER_ORDER]
        g['ok'], g['reason'] = True, ''
        try:
            hrs = (now - datetime.datetime.fromisoformat(last)).total_seconds() / 3600 if last else None
        except ValueError:
            hrs = None
        if hrs is not None and hrs < GAP_H:
            g['ok'], g['reason'] = False, f'напоминали {hrs:.0f} ч назад'
        elif not left_orders:
            g['ok'], g['reason'] = False, f'уже {MAX_PER_ORDER} напоминания по заказу'
        elif n_ok >= MAX_PER_RUN:
            g['ok'], g['reason'] = False, f'лимит {MAX_PER_RUN} за раз, повторите позже'
        if g['ok']:
            n_ok += 1
            g['orders'] = left_orders
            R['groups'][g['buyer']] = {'name': g['name'], 'orders': [o['id'] for o in left_orders]}
        groups.append(g)
    return {'groups': groups, 'counts': cnt}


def send_one(buyer, template):
    g = R['groups'].get(buyer)
    if not g:
        raise fm.Stop('Этого покупателя нет в последнем списке. Нажмите «Найти заказы» заново. Ничего не отправлено.')
    log = read_log()
    last = log['buyers'].get(buyer)
    try:
        if last and (datetime.datetime.now() - datetime.datetime.fromisoformat(last)).total_seconds() < GAP_H * 3600:
            raise fm.Stop('Этому покупателю напоминание уже ушло меньше 24 часов назад. Ничего не отправлено.')
    except ValueError:
        pass
    text = template.replace('{order}', ', '.join('#' + o for o in g['orders']))
    me = int(acc.S['me']['uid'])
    node = f'users-{min(me, int(buyer))}-{max(me, int(buyer))}'
    res = chat.send(node, text)
    if not res['error_site']:
        now = datetime.datetime.now().isoformat(timespec='seconds')
        log['buyers'][buyer] = now
        for o in g['orders']:
            log['orders'][o] = int(log['orders'].get(o, 0)) + 1
        write_log(log)
        R['groups'].pop(buyer, None)
    return {'note': res['note'], 'error_site': res['error_site']}


def handle(method, path, b):
    if method != 'POST':
        return 405, {'error': 'Только POST'}
    if not acc.S['key']:
        return 409, {'error': 'Сначала войдите.'}
    if path == '/api/remind/preview':
        return acc.guarded(scan)
    if path == '/api/remind/send':
        buyer, text = str(b.get('buyer', '')), str(b.get('text', '')).strip()
        if not re.fullmatch(r'\d{1,15}', buyer):
            return 400, {'error': 'Неверный ID покупателя'}
        if not text or len(text) > MAX_TEXT:
            return 400, {'error': f'Текст пустой или длиннее {MAX_TEXT} символов.'}
        return acc.guarded(lambda: send_one(buyer, text))
    return 404, {'error': 'Нет такого действия'}


HTML = r'''
<div class="box" id="rm-box" style="margin-top:12px"><h3>Напоминания о подтверждении заказа</h3>
<div class="cnt">Заказы «Оплачен» старше 24 часов. Сначала «Найти заказы»: ничего не отправляется, вы видите список и можете снять галочки. Покупателю, которому напоминали меньше 24 часов назад, не пишем; на заказ не больше 3 напоминаний; за раз не больше 30 покупателей. Номера заказов подставляются вместо {order}.</div>
<textarea id="rm-text" rows="3" maxlength="1000" style="width:100%;margin-top:8px;font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 8px">Здравствуйте! Заказ {order} оплачен больше суток назад. Если всё работает, пожалуйста, подтвердите выполнение заказа на сайте FunPay. Спасибо!</textarea>
<div class="bar" style="margin-top:6px"><button type="button" id="rm-scan">Найти заказы</button>
<button type="button" id="rm-go" disabled>Отправить выбранным</button></div>
<div class="cnt" id="rm-sum"></div><div id="rm-tbl"></div></div>
'''

JS = r'''
/* ---------- Напоминания ---------- */
var RM={groups:[],checks:{}};
function rmRender(){
  var box=$('rm-tbl');box.textContent='';
  var t=el('table'),th=el('thead'),hr=el('tr');
  ['','Покупатель','Заказы (возраст, ч)','Статус'].forEach(function(h){hr.appendChild(el('th','',h));});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  RM.groups.forEach(function(g){
    var tr=el('tr'),td=el('td','');
    if(g.ok){var c=el('input');c.type='checkbox';c.checked=true;RM.checks[g.buyer]=c;td.appendChild(c);}
    tr.appendChild(td);tr.appendChild(el('td','',g.name+' (ID '+g.buyer+')'));
    tr.appendChild(el('td','',g.orders.map(function(o){return '#'+o.id+' ('+o.age+' ч'+(o.sent?', напоминаний: '+o.sent:'')+')';}).join(', ')));
    g.stTd=el('td','',g.ok?'будет отправлено':'пропуск: '+g.reason);tr.appendChild(g.stTd);tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(t);
  if(!RM.groups.length)box.appendChild(el('div','empty','Подходящих заказов нет.'));
  var n=RM.groups.filter(function(g){return g.ok;}).length;
  $('rm-go').disabled=!n;
}
function rmScan(){
  say('Загружаю заказы…');RM.checks={};
  ap('/api/remind/preview').then(function(d){
    RM.groups=d.groups;var c=d.counts;
    $('rm-sum').textContent='На странице заказов: '+c.on_page+', «Оплачен»: '+c.paid+', моложе 24 ч: '+c.young+
      ', не разобрана дата: '+c.no_date+', не нашёл покупателя: '+c.no_buyer+'. Показана только первая страница списка заказов.';
    rmRender();say('');
  }).catch(function(e){say(e.message,true);});
}
function rmGo(){
  var todo=RM.groups.filter(function(g){return g.ok&&RM.checks[g.buyer]&&RM.checks[g.buyer].checked;}),i=0;
  if(!todo.length){say('Не выбрано ни одного покупателя.');return;}
  var txt=$('rm-text').value.trim();
  if(!txt){say('Текст пустой.',true);return;}
  if(!confirm('Отправить напоминание '+todo.length+' покупателям? Это отдельные сообщения в их чаты, по одному с паузой. При ошибке остановлюсь.'))return;
  $('rm-go').disabled=true;$('rm-scan').disabled=true;
  (function next(){
    if(i>=todo.length){$('rm-scan').disabled=false;say('Готово: прошли всех выбранных. Проверьте результат в таблице и в чатах.');return;}
    var g=todo[i++];say('Отправляю '+i+' из '+todo.length+'…');
    ap('/api/remind/send',{buyer:g.buyer,text:txt}).then(function(d){
      g.stTd.textContent=d.error_site?('ошибка сайта: '+d.error_site):'запрос отправлен';
      if(d.error_site){$('rm-scan').disabled=false;say(d.note,true);return;}
      next();
    }).catch(function(e){$('rm-scan').disabled=false;say(e.message,true);});
  })();
}
$('rm-scan').addEventListener('click',rmScan);
$('rm-go').addEventListener('click',rmGo);
'''
