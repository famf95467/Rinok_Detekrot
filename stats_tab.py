# -*- coding: utf-8 -*-
"""Статистика во вкладке «Аккаунт» (версия 1): ваши продажи, прибыльные и слабые лоты, позиция по цене,
кандидаты на повышение цены, баланс и аватарка. Нужны рядом account_tab.py и funpay_manage.py.

Откуда данные:
  заказы: страница /orders/trade (кнопка «Обновить заказы», по одному запросу на страницу списка, с паузами).
          Копится локально в orders_cache.json: номер заказа, статус, цена, название, время. Покупателей и переписку не хранит.
  рынок:  последняя сохранённая страница категории (те же данные, что на экране «Цены»), никаких новых запросов.
  затраты: себестоимость каждого лота вы вводите сами (lot_costs.json): сайт её не знает. Комиссию тоже задаёте сами.
Прибыль = подтверждённая выручка минус комиссия, минус себестоимость на каждый подтверждённый заказ. Это оценка.
«Выручка» считается по заказам со статусом «Закрыт» (подтверждены), «Оплачен» показан отдельно как ожидающий, «Возврат» не в выручке.
Дата заказа это дата оплаты, а не подтверждения.
Разметка /orders/trade, пагинация и баланс написаны по памяти и НЕ проверены на живом сайте: что не нашлось, то пропускается
и показывается в счётчиках; если нет совсем ничего, программа покажет список классов без содержимого заказов."""
import datetime, json, os, re, statistics
from bs4 import BeautifulSoup
import funpay_manage as fm
import account_tab as acc

CTX = {}                       # detector_app кладёт сюда api_prices (данные рынка)
CACHE = os.path.join(fm.HERE, 'orders_cache.json')
COSTS = os.path.join(fm.HERE, 'lot_costs.json')
MAX_PAGES = 20
MIN_ORDERS_7D = 3              # сколько заказов за 7 дней считается «высокой активностью»
RAISE_MAX = 1.25               # подсказка не выше +25% к текущей цене
MONTHS = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
          'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
STATUS = {'оплачен': 'paid', 'закрыт': 'closed', 'возврат': 'refund'}


def jread(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else default
    except (OSError, ValueError):
        return default


def jwrite(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def key40(title):
    t = re.sub(r',\s*(GTA 5|SAMP),\s*[^,]+$', '', title or '')
    return re.sub(r'\s+', ' ', t).strip().casefold()[:40]


def parse_dt(absd, left, now):
    s = (absd or '').strip().lower()
    try:
        m = re.match(r'(сегодня|вчера),?\s*(\d{1,2}):(\d{2})', s)
        if m:
            d = now.date() - datetime.timedelta(days=1 if m.group(1) == 'вчера' else 0)
            return datetime.datetime(d.year, d.month, d.day, int(m.group(2)), int(m.group(3)))
        m = re.match(r'(\d{1,2})\s+([а-я]+)(?:\s+(\d{4}))?,?\s*(\d{1,2}):(\d{2})', s)
        if m and m.group(2) in MONTHS:
            y = int(m.group(3)) if m.group(3) else now.year
            t = datetime.datetime(y, MONTHS[m.group(2)], int(m.group(1)), int(m.group(4)), int(m.group(5)))
            return t.replace(year=y - 1) if (t > now and not m.group(3)) else t
    except ValueError:
        pass
    s = (left or '').strip().lower()
    m = re.search(r'(\d+)?\s*(минут|мин\b|час|д(?:ень|ня|ней)|недел|месяц)', s)
    if m and 'назад' in s:
        n = int(m.group(1)) if m.group(1) else 1
        u = m.group(2)
        hours = n / 60 if u.startswith('мин') else n if u.startswith('час') else n * 24 if u.startswith('д') \
            else n * (168 if u.startswith('недел') else 720)
        return now - datetime.timedelta(hours=hours)
    return None


def parse_orders(soup, now):
    rows = []
    for it in soup.select('a.tc-item'):
        st = it.select_one('.tc-status')
        m = re.search(r'/orders/([A-Za-z0-9]+)', it.get('href', ''))
        status = STATUS.get(st.get_text(strip=True).casefold()) if st else None
        if not st or not m or not status:
            continue
        p = it.select_one('.tc-price')
        ptxt = p.get_text(' ', strip=True) if p else ''
        num = re.sub(r'[^\d.,]', '', ptxt).replace(',', '.')
        try:
            price = float(num) if num else None
        except ValueError:
            price = None
        left, absd = it.select_one('.tc-date-left'), it.select_one('.tc-date-time')
        dt = parse_dt(absd.get_text(' ', strip=True) if absd else '', left.get_text(' ', strip=True) if left else '', now)
        t = it.select_one('.order-desc div')
        rows.append({'id': m.group(1), 'status': status, 'price': price, 'cur': '₽' if '₽' in ptxt else (ptxt[-1:] or '?'),
                     'title': t.get_text(' ', strip=True)[:120] if t else '',
                     'ts': dt.isoformat(timespec='minutes') if dt else None})
    return rows


def _classes(soup):
    seen = set()
    for e in soup.find_all(True):
        for c in e.get('class', []):
            if c.startswith(('tc-', 'order')):
                seen.add(c)
    return ', '.join(sorted(seen)[:40]) or '(нет)'


def sync(pages):
    key, now = acc.S['key'], datetime.datetime.now()
    cache = jread(CACHE, {'orders': {}})
    orders = cache.setdefault('orders', {})
    _, _, html = fm.request('/orders/trade', key)
    used, got, new, seen_cont = 1, 0, 0, set()
    while True:
        soup = BeautifulSoup(html, 'html.parser')
        rows = parse_orders(soup, now)
        if used == 1 and not rows:
            raise fm.Stop('Заказы на странице /orders/trade не найдены: разметка другая или заказов нет. Классы на странице '
                          '(без содержимого заказов): ' + _classes(soup) + '. Пришлите мне этот список.')
        for r in rows:
            got += 1
            old = orders.get(r['id'])
            if not old:
                new += 1
            elif not r['ts']:
                r['ts'] = old.get('ts')
            orders[r['id']] = r
        cont = soup.find('input', attrs={'name': 'continue'})
        val = cont.get('value') if cont else ''
        if used >= pages or not rows or not val or val in seen_cont:
            break
        seen_cont.add(val)
        _, _, html = fm.request('/orders/trade', key, data={'continue': val}, referer='/orders/trade')
        used += 1
    cache['updated'] = now.isoformat(timespec='seconds')
    jwrite(CACHE, cache)
    return {'pages': used, 'got': got, 'new': new, 'total': len(orders),
            'more': bool(val) and used >= pages}


def profile():
    _, _, html = fm.request('/', acc.S['key'])
    soup = BeautifulSoup(html, 'html.parser')
    bal = ''
    for sel in ('.badge-balance', '.user-link-balance', '.balance'):
        e = soup.select_one(sel)
        if e and e.get_text(strip=True):
            bal = e.get_text(' ', strip=True)
            break
    return {'balance': bal, 'note': '' if bal else 'Баланс на главной странице не нашёл: разметка другая.'}


def _ts(o):
    try:
        return datetime.datetime.fromisoformat(o['ts']) if o.get('ts') else None
    except ValueError:
        return None


def report(days):
    cache = jread(CACHE, {'orders': {}})
    cfg = jread(COSTS, {'fee': 0, 'costs': {}})
    fee = float(cfg.get('fee') or 0)
    costs = cfg.get('costs', {})
    now = datetime.datetime.now()
    since = now - datetime.timedelta(days=days) if days else None
    allo = [o for o in cache.get('orders', {}).values() if o.get('cur') == '₽' and o.get('price') is not None]
    per = [o for o in allo if _ts(o) and (since is None or _ts(o) >= since)]
    tot = {'closed': 0, 'paid': 0, 'refund': 0, 'rev': 0.0, 'pending': 0.0, 'refund_sum': 0.0}
    lots = {}
    w7 = now - datetime.timedelta(days=7)
    for o in per:
        tot[o['status']] += 1
        k = key40(o['title'])
        g = lots.setdefault(k, {'key': k, 'title': re.sub(r',\s*(GTA 5|SAMP),\s*[^,]+$', '', o['title']), 'closed': 0,
                                'paid': 0, 'refund': 0, 'rev': 0.0, 'pending': 0.0, 'n7': 0})
        g[o['status']] += 1
        if o['status'] == 'closed':
            tot['rev'] += o['price']; g['rev'] += o['price']
        elif o['status'] == 'paid':
            tot['pending'] += o['price']; g['pending'] += o['price']
        else:
            tot['refund_sum'] += o['price']
        if _ts(o) >= w7 and o['status'] != 'refund':
            g['n7'] += 1
    rows = []
    for g in lots.values():
        c = costs.get(g['key'])
        g['cost'] = c
        g['profit'] = round(g['rev'] * (1 - fee / 100) - float(c) * g['closed'], 2) if c not in (None, '') else None
        rows.append(g)
    have_cost = any(r['profit'] is not None for r in rows)
    rows.sort(key=lambda r: -(r['profit'] if (have_cost and r['profit'] is not None) else (r['rev'] if not have_cost else -1e18)))
    lead = {r['key'] for r in rows[:3] if r['closed']}
    for r in rows:
        tags = []
        if r['key'] in lead:
            tags.append('лидер')
        if r['profit'] is not None and r['profit'] <= 0 and r['closed']:
            tags.append('убыточный')
        if r['refund'] >= 2 and r['refund'] >= r['closed']:
            tags.append('много возвратов')
        r['tags'] = ', '.join(tags)
        r['rev'], r['pending'] = round(r['rev']), round(r['pending'])
    daily = []
    for i in range(13, -1, -1):
        d = (now - datetime.timedelta(days=i)).date()
        sel = [o for o in allo if _ts(o) and _ts(o).date() == d and o['status'] == 'closed']
        daily.append({'date': d.isoformat()[5:], 'n': len(sel), 'rev': round(sum(o['price'] for o in sel))})
    nodate = sum(1 for o in cache.get('orders', {}).values() if not o.get('ts'))
    return {'updated': cache.get('updated', ''), 'orders_total': len(cache.get('orders', {})), 'nodate': nodate,
            'fee': fee, 'days': days, 'tot': {k: (round(v) if isinstance(v, float) else v) for k, v in tot.items()},
            'lots': rows, 'daily': daily, 'have_cost': have_cost}


def position():
    f = CTX.get('prices')
    if not f:
        raise fm.Stop('Данные рынка недоступны (программа не передала их модулю).')
    d = f('')
    lots = d.get('lots') or []
    if not lots:
        return {'rows': [], 'note': d.get('note') or 'В расчёте цен нет ни одного лота: отметьте лоты на экране «Отметки».'}
    nick = acc.S['me']['nick']
    mine = [l for l in lots if l['seller'] == nick]
    if not mine:
        return {'rows': [], 'note': f'Ваших лотов среди скриптов в расчёте нет: ник «{nick}» на странице {d.get("date") or ""} не найден '
                                    '(лоты не в категории, не прошли правила или не отмечены).'}
    prices = [l['price'] for l in lots]
    med = statistics.median(prices)
    now = datetime.datetime.now()
    cnt7, cnt30 = {}, {}
    for o in jread(CACHE, {'orders': {}}).get('orders', {}).values():
        t = _ts(o)
        if not t or o.get('status') == 'refund':
            continue
        k = key40(o['title'])
        if t >= now - datetime.timedelta(days=30):
            cnt30[k] = cnt30.get(k, 0) + 1
        if t >= now - datetime.timedelta(days=7):
            cnt7[k] = cnt7.get(k, 0) + 1
    rows = []
    for l in sorted(mine, key=lambda x: x['price']):
        k = key40(l['title'])
        n7, n30 = cnt7.get(k, 0), cnt30.get(k, 0)
        rank = 1 + sum(1 for p in prices if p < l['price'])
        sug = None
        if n7 >= MIN_ORDERS_7D and l['price'] <= med:
            sug = round(min(max(med, l['price']), l['price'] * RAISE_MAX))
            if sug <= l['price']:
                sug = None
        rows.append({'title': l['title'], 'price': l['price'], 'rank': rank, 'of': len(prices), 'median': round(med),
                     'n7': n7, 'n30': n30, 'suggest': sug})
    return {'rows': rows, 'date': d.get('date') or '', 'note': ''}


def handle(method, path, b):
    if method != 'POST':
        return 405, {'error': 'Только POST'}
    if path == '/api/stat/report':
        days = b.get('days', 30)
        if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 3650:
            return 400, {'error': 'Неверный период'}
        return 200, report(days)
    if path == '/api/stat/cost':
        title, cost = str(b.get('title', '')), b.get('cost', '')
        k = key40(title)
        if not k:
            return 400, {'error': 'Пустое название лота'}
        cfg = jread(COSTS, {'fee': 0, 'costs': {}})
        cfg.setdefault('costs', {})
        if cost in ('', None):
            cfg['costs'].pop(k, None)
        else:
            try:
                v = float(str(cost).replace(',', '.'))
            except ValueError:
                return 400, {'error': 'Себестоимость должна быть числом'}
            if not 0 <= v <= 10 ** 7:
                return 400, {'error': 'Себестоимость вне допустимых пределов'}
            cfg['costs'][k] = v
        jwrite(COSTS, cfg)
        return 200, {'ok': True}
    if path == '/api/stat/fee':
        try:
            v = float(str(b.get('fee', '')).replace(',', '.'))
        except ValueError:
            return 400, {'error': 'Комиссия должна быть числом'}
        if not 0 <= v <= 50:
            return 400, {'error': 'Комиссия от 0 до 50 %'}
        cfg = jread(COSTS, {'fee': 0, 'costs': {}})
        cfg['fee'] = v
        jwrite(COSTS, cfg)
        return 200, {'ok': True}
    if not acc.S['key']:
        return 409, {'error': 'Сначала войдите.'}
    if path == '/api/stat/profile':
        return acc.guarded(profile)
    if path == '/api/stat/position':
        return acc.guarded(position)
    if path == '/api/stat/sync':
        pages = b.get('pages', 3)
        if not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= MAX_PAGES:
            return 400, {'error': f'Страниц от 1 до {MAX_PAGES}'}
        return acc.guarded(lambda: sync(pages))
    return 404, {'error': 'Нет такого действия'}


HTML = r'''
<div class="box" id="st-box" style="margin-top:12px"><h3>Статистика</h3>
<div class="bar"><img id="st-ava" alt="" width="40" height="40" style="border-radius:50%;display:none">
<div><div class="sv" id="st-nick" style="font-size:16px"></div><div class="cnt" id="st-bal">Баланс: нажмите «Обновить баланс»</div></div>
<button type="button" id="st-balbtn">Обновить баланс</button></div>
<div class="cnt">Данные о ваших заказах копятся локально (orders_cache.json). Выручка считается по заказам «Закрыт», «Оплачен» показан отдельно, возвраты не в выручке. Прибыль это оценка: нужна себестоимость, её вводите вы в таблице лотов.</div>
<div class="bar" style="margin-top:8px"><label>Страниц списка заказов: <input type="number" id="st-pages" min="1" max="20" value="3" style="width:64px"></label>
<button type="button" id="st-sync">Обновить заказы</button>
<label>Период: <select id="st-days"><option value="7">7 дней</option><option value="30" selected>30 дней</option><option value="90">90 дней</option><option value="0">всё время</option></select></label>
<label>Комиссия, %: <input type="number" id="st-fee" min="0" max="50" step="0.1" style="width:70px"></label>
<button type="button" id="st-feebtn">Сохранить</button></div>
<div class="cnt" id="st-sum"></div>
<div id="st-daily"></div>
<h3 style="margin-top:14px">Лоты: что приносит деньги, что нет</h3>
<div id="st-lots"></div>
<h3 style="margin-top:14px">Позиция по цене и где можно поднять</h3>
<div class="bar"><button type="button" id="st-pos">Показать позицию</button></div>
<div class="cnt" id="st-posnote"></div><div id="st-postbl"></div></div>
'''

JS = r'''
/* ---------- Статистика ---------- */
function stM(v){return (v===null||v===undefined)?'—':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:0})+' ₽';}
function stProfile(){
  if($('ac-main').style.display!=='block')return Promise.resolve();
  return api('/api/acc/status').then(function(s){
    $('st-nick').textContent=s.nick||'';var im=$('st-ava');
    if(s.avatar){im.src=s.avatar;im.style.display='inline-block';}else im.style.display='none';
  }).then(function(){return ap('/api/stat/profile');}).then(function(d){
    $('st-bal').textContent=d.balance?('Баланс: '+d.balance):d.note;
  }).catch(function(e){say(e.message,true);});
}
function stReport(){
  return ap('/api/stat/report',{days:Number($('st-days').value)}).then(function(d){
    $('st-fee').value=d.fee;
    var t=d.tot;
    $('st-sum').textContent='Заказов в базе: '+d.orders_total+(d.updated?' (обновлено '+d.updated.replace('T',' ')+')':' (ещё не загружали)')+
      '. За период: подтверждено '+t.closed+' на '+stM(t.rev)+', ждут подтверждения '+t.paid+' на '+stM(t.pending)+', возвратов '+t.refund+' на '+stM(t.refund_sum)+
      '.'+(d.nodate?' Без распознанной даты: '+d.nodate+' (в периоды не входят).':'');
    var box=$('st-daily');box.textContent='';
    var mx=Math.max.apply(null,d.daily.map(function(x){return x.rev;}).concat([1]));
    d.daily.forEach(function(x){
      var r=el('div','bar');r.style.margin='1px 0';
      r.appendChild(el('span','cnt',x.date));
      var b=el('div','');b.style.cssText='height:10px;border-radius:3px;background:var(--acc);width:'+Math.round(x.rev/mx*260)+'px;min-width:2px';
      r.appendChild(b);r.appendChild(el('span','cnt',stM(x.rev)+' · '+x.n+' зак.'));box.appendChild(r);});
    box.insertBefore(el('div','cnt','Подтверждённая выручка по дням, последние 14 (по дате оплаты заказа):'),box.firstChild);
    var lb=$('st-lots');lb.textContent='';
    if(!d.lots.length){lb.appendChild(el('div','empty','Нет заказов за период. Нажмите «Обновить заказы».'));return;}
    var tb=el('table'),th=el('thead'),hr=el('tr');
    ['Лот','За 7 дн.','Подтв.','Ждут','Возвр.','Выручка','Себестоимость за 1 шт., ₽','Прибыль (оценка)','Метка'].forEach(function(h,i){hr.appendChild(el('th',i>0&&i<8?'num':'',h));});
    th.appendChild(hr);tb.appendChild(th);var bd=el('tbody');
    d.lots.forEach(function(r){
      var tr=el('tr');tr.appendChild(el('td','',r.title));
      [r.n7,r.closed,r.paid,r.refund].forEach(function(v){tr.appendChild(el('td','num',String(v)));});
      tr.appendChild(el('td','num',stM(r.rev)));
      var td=el('td','num'),inp=el('input');inp.type='number';inp.min='0';inp.step='any';inp.style.width='90px';
      inp.value=(r.cost===null||r.cost===undefined)?'':r.cost;
      inp.addEventListener('change',function(){ap('/api/stat/cost',{title:r.title,cost:inp.value}).then(stReport).catch(function(e){say(e.message,true);});});
      td.appendChild(inp);tr.appendChild(td);
      var pr=el('td','num',stM(r.profit));if(r.profit!==null&&r.profit<=0)pr.className='num warn';tr.appendChild(pr);
      tr.appendChild(el('td','',r.tags));bd.appendChild(tr);});
    tb.appendChild(bd);lb.appendChild(tb);
    var titles={};d.lots.forEach(function(r){titles[r.title.toLowerCase().slice(0,40)]=1;});
    var idle=(typeof AC!=='undefined'?AC.rows:[]).filter(function(r){return !titles[r.title.replace(/\s+/g,' ').toLowerCase().slice(0,40)];});
    if(idle.length)lb.appendChild(el('div','cnt','Ваши лоты без заказов за период ('+idle.length+'): '+idle.slice(0,8).map(function(r){return r.title.slice(0,40);}).join('; ')+(idle.length>8?'…':'')));
  }).catch(function(e){say(e.message,true);});
}
function stSync(){
  var p=Number($('st-pages').value)||3;
  if(!confirm('Будет около '+p+' запросов страницы заказов (пауза 3–6 с между ними). Они входят в общий лимит запросов сессии. Продолжить?'))return;
  $('st-sync').disabled=true;say('Загружаю заказы…');
  ap('/api/stat/sync',{pages:p}).then(function(d){
    say('Загружено страниц: '+d.pages+', заказов на них: '+d.got+', новых: '+d.new+', всего в базе: '+d.total+(d.more?'. Есть более старые заказы: увеличьте число страниц.':'.'));
    return stReport();
  }).catch(function(e){say(e.message,true);}).then(function(){$('st-sync').disabled=false;});
}
function stPos(){
  say('Считаю позицию…');
  ap('/api/stat/position').then(function(d){
    say('');$('st-posnote').textContent=d.note||('Рынок по странице '+d.date+'. Цены витрины, это не сделки. «Можно поднять» это оценка: много заказов за 7 дней и цена не выше медианы.');
    var box=$('st-postbl');box.textContent='';if(!d.rows.length)return;
    var t=el('table'),th=el('thead'),hr=el('tr');
    ['Лот','Ваша цена','Место по цене','Медиана рынка','Заказов 7 дн.','Заказов 30 дн.','Можно поднять до (оценка)'].forEach(function(h,i){hr.appendChild(el('th',i>0?'num':'',h));});
    th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
    d.rows.forEach(function(r){var tr=el('tr');tr.appendChild(el('td','',r.title));
      tr.appendChild(el('td','num',stM(r.price)));tr.appendChild(el('td','num',r.rank+' из '+r.of));
      tr.appendChild(el('td','num',stM(r.median)));tr.appendChild(el('td','num',String(r.n7)));tr.appendChild(el('td','num',String(r.n30)));
      tr.appendChild(el('td','num',r.suggest?stM(r.suggest):'—'));tb.appendChild(tr);});
    t.appendChild(tb);box.appendChild(t);
  }).catch(function(e){say(e.message,true);});
}
$('st-sync').addEventListener('click',stSync);
$('st-pos').addEventListener('click',stPos);
$('st-balbtn').addEventListener('click',stProfile);
$('st-days').addEventListener('change',stReport);
$('st-feebtn').addEventListener('click',function(){
  ap('/api/stat/fee',{fee:$('st-fee').value}).then(function(){say('Комиссия сохранена.');return stReport();}).catch(function(e){say(e.message,true);});});
var _stLoadAcc=loadAcc;
loadAcc=function(){return _stLoadAcc().then(function(){return stReport();}).then(stProfile);};
'''
