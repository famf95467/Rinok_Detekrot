# -*- coding: utf-8 -*-
"""Сообщения во вкладке «Аккаунт» (версия 1). Нужны рядом account_tab.py и funpay_manage.py.
Показывает список ваших диалогов, историю выбранного диалога и отправляет сообщение, которое вы написали сами.
Переписка держится только в памяти браузера: на диск не пишется, в логи не попадает (в manage_log.csv только путь).
Ничего не отправляется само: одно сообщение = одно нажатие «Отправить». Автоответов и рассылок нет.
Адреса /chat/ и /runner/ написаны по памяти и НЕ проверены на живом сайте: если разметка другая,
программа скажет, что не нашла, а не будет угадывать (список классов без текста сообщений)."""
import json, re
from bs4 import BeautifulSoup
import funpay_manage as fm
import account_tab as acc

MAX_TEXT = 2000


def _classes(soup, prefixes=('chat', 'contact')):
    seen = set()
    for e in soup.find_all(True):
        for c in e.get('class', []):
            if c.startswith(prefixes):
                seen.add(c)
    return ', '.join(sorted(seen)[:40]) or '(нет)'


def list_chats():
    _, _, html = fm.request('/chat/', acc.S['key'])
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for it in soup.select('a.contact-item'):
        cid = it.get('data-id')
        if not cid or not re.fullmatch(r'\d{1,15}', str(cid)):
            continue
        name = it.select_one('.media-user-name')
        msg = it.select_one('.contact-item-message')
        tm = it.select_one('.contact-item-time')
        rows.append({'id': str(cid),
                     'name': name.get_text(' ', strip=True) if name else '(без имени)',
                     'last': msg.get_text(' ', strip=True)[:120] if msg else '',
                     'time': tm.get_text(' ', strip=True) if tm else '',
                     'unread': 'unread' in it.get('class', [])})
    if not rows:
        raise fm.Stop('Диалоги на странице /chat/ не найдены: разметка другая или диалогов нет. '
                      'Классы на странице (без текста переписки): ' + _classes(soup) + '. Пришлите мне этот список.')
    return {'rows': rows}


def history(node):
    _, _, html = fm.request(f'/chat/?node={node}', acc.S['key'])
    soup = BeautifulSoup(html, 'html.parser')
    uid = acc.S['me']['uid']
    items = soup.select('.chat-msg-item')
    if not items:
        raise fm.Stop('Сообщения в диалоге не найдены: пусто или разметка другая. '
                      'Классы на странице (без текста переписки): ' + _classes(soup) + '. Пришлите мне этот список.')
    out, author, mine = [], '', False
    for it in items:
        a = it.select_one('.chat-msg-author-link')
        if a:
            author = a.get_text(' ', strip=True)
            mine = f'/users/{uid}/' in a.get('href', '')
        t = it.select_one('.chat-msg-text')
        if not t:
            continue
        d = it.select_one('.chat-msg-date')
        out.append({'author': author, 'mine': mine, 'time': (d.get('title') or d.get_text(strip=True)) if d else '',
                    'text': t.get_text('\n', strip=True)[:3000]})
    return {'messages': out[-60:]}


def send(node, text):
    key = acc.S['key']
    page = f'/chat/?node={node}'
    _, _, html = fm.request(page, key)        # свежий csrf-токен перед отправкой
    tok = fm.app_data(html).get('csrf-token')
    if not tok:
        raise fm.Stop('Не нашёл csrf-токен, отправка невозможна. Ничего не отправлено.')
    objects = [{'type': 'chat_node', 'id': node, 'tag': '0000000000',
                'data': {'node': node, 'last_message': -1, 'content': ''}}]
    req = {'action': 'chat_message', 'data': {'node': node, 'last_message': -1, 'content': text}}
    _, _, resp = fm.request('/runner/', key, referer=page,
                            data={'objects': json.dumps(objects), 'request': json.dumps(req, ensure_ascii=False),
                                  'csrf_token': tok})
    err = ''
    try:
        j = json.loads(resp)
        r = j.get('response') if isinstance(j, dict) else None
        if isinstance(r, dict) and r.get('error'):
            err = re.sub(r'<[^>]+>', ' ', str(r['error']))[:300]
    except ValueError:
        pass
    return {'error_site': err, 'note': ('Сайт вернул ошибку: ' + err) if err else
            'Запрос отправлен. Ответ сайта программа не толкует: проверьте, что сообщение появилось в диалоге.'}


def handle(method, path, b):
    if method != 'POST':
        return 405, {'error': 'Только POST'}
    if not acc.S['key']:
        return 409, {'error': 'Сначала войдите.'}
    if path == '/api/chat/list':
        return acc.guarded(list_chats)
    node = str(b.get('node', ''))
    if not re.fullmatch(r'\d{1,15}', node):
        return 400, {'error': 'Неверный номер диалога'}
    if path == '/api/chat/history':
        return acc.guarded(lambda: history(node))
    if path == '/api/chat/send':
        text = str(b.get('text', '')).strip()
        if not text:
            return 400, {'error': 'Сообщение пустое.'}
        if len(text) > MAX_TEXT:
            return 400, {'error': f'Сообщение длиннее {MAX_TEXT} символов.'}
        return acc.guarded(lambda: send(node, text))
    return 404, {'error': 'Нет такого действия'}


HTML = r'''
<div class="box" id="ch-box" style="margin-top:12px"><h3>Сообщения</h3>
<div class="cnt">Ваши диалоги с покупателями. Переписка показывается только на экране и нигде не сохраняется. Одно нажатие «Отправить» = одно сообщение, автоответов нет. Каждое открытие списка или диалога это один запрос к сайту (с паузой).</div>
<div class="bar" style="margin-top:8px"><button type="button" id="ch-load">Загрузить диалоги</button>
<input type="text" id="ch-q" placeholder="Поиск по имени" style="max-width:220px"></div>
<div id="ch-list"></div>
<div id="ch-pane" style="display:none;margin-top:10px">
<div class="bar"><div class="sv" id="ch-title" style="font-size:16px"></div><button type="button" id="ch-refresh">Обновить диалог</button></div>
<div id="ch-msgs" style="max-height:340px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:8px;background:var(--bg)"></div>
<textarea id="ch-text" rows="3" maxlength="2000" placeholder="Ваше сообщение" style="width:100%;margin-top:8px;font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 8px"></textarea>
<div class="bar" style="margin-top:6px"><button type="button" id="ch-send">Отправить</button></div>
</div></div>
'''

JS = r'''
/* ---------- Сообщения ---------- */
var CH={list:[],cur:null};
function chRender(){
  var q=$('ch-q').value.trim().toLowerCase(),box=$('ch-list');box.textContent='';
  var rows=CH.list.filter(function(r){return !q||r.name.toLowerCase().indexOf(q)>=0;});
  var t=el('table'),th=el('thead'),hr=el('tr');
  ['','Собеседник','Последнее сообщение','Время'].forEach(function(h){hr.appendChild(el('th','',h));});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  rows.slice(0,200).forEach(function(r){
    var tr=el('tr'),td=el('td','btns'),b=el('button','b','Открыть');b.type='button';
    b.addEventListener('click',function(){chOpen(r);});td.appendChild(b);tr.appendChild(td);
    var n=el('td','',r.name);if(r.unread)n.appendChild(el('span','tag','новое'));
    tr.appendChild(n);tr.appendChild(el('td','',r.last));tr.appendChild(el('td','',r.time));tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(t);
  if(!rows.length)box.appendChild(el('div','empty','Диалогов нет.'));
}
function chLoad(){
  say('Загружаю диалоги…');
  return ap('/api/chat/list').then(function(d){CH.list=d.rows;chRender();say('');}).catch(function(e){say(e.message,true);});
}
function chOpen(r){
  CH.cur=r;$('ch-title').textContent=r.name;$('ch-pane').style.display='block';$('ch-text').value='';chHist();
}
function chHist(){
  if(!CH.cur)return;
  say('Загружаю диалог…');
  return ap('/api/chat/history',{node:CH.cur.id}).then(function(d){
    var box=$('ch-msgs');box.textContent='';
    d.messages.forEach(function(m){
      var w=el('div','');w.style.cssText='margin:0 0 8px;padding:6px 9px;border-radius:6px;background:'+(m.mine?'var(--sbg)':'var(--card)')+';border:1px solid var(--line)';
      w.appendChild(el('div','cnt',(m.mine?'Вы':m.author)+(m.time?' · '+m.time:'')));
      var t=el('div','',m.text);t.style.whiteSpace='pre-wrap';w.appendChild(t);box.appendChild(w);});
    box.scrollTop=box.scrollHeight;say('');
  }).catch(function(e){say(e.message,true);});
}
function chSend(){
  var txt=$('ch-text').value.trim();
  if(!CH.cur||!txt){say('Напишите текст сообщения.');return;}
  var b=$('ch-send');b.disabled=true;say('Отправляю…');
  ap('/api/chat/send',{node:CH.cur.id,text:txt}).then(function(d){
    if(!d.error_site)$('ch-text').value='';
    say(d.note,!!d.error_site);return chHist();
  }).catch(function(e){say(e.message,true);}).then(function(){b.disabled=false;});
}
$('ch-load').addEventListener('click',chLoad);
$('ch-q').addEventListener('input',chRender);
$('ch-refresh').addEventListener('click',chHist);
$('ch-send').addEventListener('click',chSend);
'''
