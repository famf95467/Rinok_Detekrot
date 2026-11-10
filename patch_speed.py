# -*- coding: utf-8 -*-
"""Правит funpay_manage.py и account_tab.py (рядом с этим файлом), делает копии .bak.

1) Вход: если есть golden_key.txt (галочка «Запомнить»), вкладка «Аккаунт» входит сама.
2) Количество грузится само при открытии вкладки: сначала одним запросом на раздел (страница /lots/N/trade,
   колонка «Наличие»), потом, только для лотов без числа, формой лота. Результат кэшируется в
   amounts_cache.json (только числа), свежим считается 5 минут.
3) Лоты, у которых в названии раздела есть «Услуг», не грузятся: в количестве прочерк.
4) Скорость: пауза между запросами теперь не «перед каждым», а только если с прошлого запроса прошло меньше
   0,8–1,5 с. Первый запрос после простоя идёт сразу. Лимит 300 запросов за сессию снят
   (он нужен только консольной версии). При блокировке, капче и т.п. всё по-прежнему останавливается.
Если какое-то место не найдено ровно один раз, ничего не меняет."""
import os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def patch(name, edits, marker):
    path = os.path.join(HERE, name)
    src = open(path, encoding='utf-8').read()
    if marker in src:
        print(f'{name}: уже применено.')
        return None
    for old, new in edits:
        if src.count(old) != 1:
            sys.exit(f'СТОП ({name}): не нашёл ровно одно место: {old[:70]!r}. Ничего не изменено. Пришлите мне этот вывод.')
        src = src.replace(old, new, 1)
    return path, src


FM = [
    (r'''HERE = os.path.dirname(os.path.abspath(__file__))
sent = 0
''', r'''HERE = os.path.dirname(os.path.abspath(__file__))
sent = 0
last_ts = 0.0
'''),
    (r'''    global sent
    if sent >= MAX_REQUESTS:
        raise Stop('Лимит запросов за запуск исчерпан.')
    if sent:
        time.sleep(random.uniform(*PACE))
    sent += 1
''', r'''    global sent, last_ts
    if sent >= MAX_REQUESTS:
        raise Stop('Лимит запросов за запуск исчерпан.')
    if sent:
        gap = random.uniform(*PACE) - (time.time() - last_ts)
        if gap > 0:
            time.sleep(gap)
    sent += 1
    last_ts = time.time()
'''),
]

AT = []
AT.append((r'''import base64, json, os, re, secrets, threading, urllib.request''',
           r'''import base64, json, os, re, secrets, threading, time, urllib.request'''))

AT.append((r'''fm.MAX_REQUESTS = 300
fm.PACE = (3, 6)
''', r'''fm.MAX_REQUESTS = 10 ** 9          # лимит «за запуск» нужен только консольной версии
fm.PACE = (0.8, 1.5)               # минимальный промежуток между запросами
fm.ALIASES.setdefault('secrets', r'^secrets$')
CACHE = os.path.join(fm.HERE, 'amounts_cache.json')
FRESH_SEC = 300
ACACHE = {}


def _cache_load():
    try:
        with open(CACHE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


ACACHE.update(_cache_load())


def _cache_save():
    tmp = CACHE + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(ACACHE, f, ensure_ascii=False)
        os.replace(tmp, CACHE)
    except OSError:
        pass


def is_service(section):
    return bool(re.search(r'услуг', section or '', re.I))


'''))

AT.append((r'''def status():''', r'''def load_node_amounts(node):
    # количество всех лотов раздела одним запросом: страница /lots/N/trade (колонка «Наличие»)
    _, _, html = fm.request(f'/lots/{node}/trade', S['key'])
    soup = BeautifulSoup(html, 'html.parser')
    out, now = {}, time.time()
    for it in soup.select('a.tc-item'):
        oid = it.get('data-offer') or (it.get('href') or '').split('id=')[-1]
        am = it.select_one('.tc-amount')
        digits = re.sub(r'\D', '', am.get_text()) if am else ''
        if oid and digits:
            out[oid] = digits
            ACACHE[oid] = {'a': digits, 't': now}
    _cache_save()
    return {'amounts': out}


def load_amount(node, offer):
    # количество одного лота из формы; при автовыдаче это число строк списка товаров, сам список не сохраняется
    _, _, html = fm.request(f'/lots/offerEdit?node={node}&offer={offer}', S['key'])
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.find('form', class_=re.compile('offer|edit', re.I)) or soup.find('form')
    if not form:
        raise fm.Stop('Форма лота не найдена, количество не загружено.')
    fields, boxes, cbs = fm.form_fields(form)
    names = set(fields) | set(boxes)
    areal, sreal, mreal = find_name('auto', names), find_name('secrets', names), find_name('amount', names)
    if areal and areal in fields and sreal:
        val = str(len([x for x in fields.get(sreal, '').replace('\r', '').split('\n') if x.strip()]))
    elif mreal:
        val = str(fields.get(mreal, ''))
    else:
        val = ''
    ACACHE[offer] = {'a': val, 't': time.time()}
    _cache_save()
    return {'amount': val}


def status():'''))

AT.append((r'''    return {'rows': rows}
''', r'''    now = time.time()
    for r in rows:
        if is_service(r['section']):
            r['svc'], r['amount'], r['fresh'] = True, '—', True
            continue
        c = ACACHE.get(r['id'])
        if c:
            r['amount'] = c.get('a', '')
            r['fresh'] = now - c.get('t', 0) < FRESH_SEC
    return {'rows': rows}
'''))

AT.append((r'''    off = str(b.get('id', ''))
''', r'''    if path == '/api/acc/nodeamounts':
        node = str(b.get('node', ''))
        if not re.fullmatch(r'\d{1,8}', node):
            return 400, {'error': 'Неверный номер раздела'}
        return guarded(lambda: load_node_amounts(node))
    off = str(b.get('id', ''))
'''))

AT.append((r'''    if path == '/api/acc/form':
''', r'''    if path == '/api/acc/amount':
        node = str(b.get('node', ''))
        if not re.fullmatch(r'\d{1,8}', node):
            return 400, {'error': 'Неверный номер раздела'}
        return guarded(lambda: load_amount(node, off))
    if path == '/api/acc/form':
'''))

AT.append((r'''    return {'status': status, 'resp': resp}
''', r'''    ACACHE.pop(offer, None)
    return {'status': status, 'resp': resp}
'''))

# ---------- JS и HTML ----------
AT.append((r'''    if(!s.logged)return;
''', r'''    if(!s.logged){
      if(s.keyfile&&!s.locked&&!AC.autoTried){AC.autoTried=true;accLogin(true);}
      return;}
'''))

AT.append((r'''AC.rows=d.rows;accRender();say('');''', r'''AC.rows=d.rows;accRender();say('');accLoadAmounts(false);'''))

AT.append((r'''tr.appendChild(el('td','num',r.amount||'нет на странице'));''',
           r'''tr.appendChild(el('td','num',r.amount||(AC.busy?'…':'—')));'''))

AT.append((r'''$('ac-amt').addEventListener('click',accAmounts);''',
           r'''$('ac-amt').addEventListener('click',function(){accLoadAmounts(true);});'''))

AT.append((r'''title="Открывает форму каждого лота без числа, по одному запросу с паузой">Узнать количество</button>''',
           r'''title="Заново загружает количество у всех лотов, кроме услуг">Обновить количество</button>'''))

AT.append((r'''Запомнить в golden_key.txt на этом ПК (простым текстом)</label>''',
           r'''Запомнить в golden_key.txt на этом ПК (простым текстом); тогда вход будет автоматическим</label>'''))

AT.append((r'''function accEdit(r){''', r'''function accLoadAmounts(force){
  if(AC.busy)return;
  var todo=AC.rows.filter(function(r){return !r.svc&&(force||!r.fresh);});
  if(!todo.length)return;
  var nodes=[],seen={},i=0;
  todo.forEach(function(r){r.got=false;if(r.node&&!seen[r.node]){seen[r.node]=1;nodes.push(r.node);}});
  AC.busy=true;$('ac-amt').disabled=true;accRender();
  function done(){AC.busy=false;$('ac-amt').disabled=false;say('');accRender();}
  function fail(e){AC.busy=false;$('ac-amt').disabled=false;accRender();say(e.message,true);}
  function phase2(){
    var rest=todo.filter(function(r){return !r.got;}),j=0;
    (function next(){
      if(j>=rest.length){done();return;}
      var r=rest[j++];say('Загружаю количество лота '+j+' из '+rest.length+'…');
      ap('/api/acc/amount',{node:r.node,id:r.id}).then(function(d){
        r.amount=d.amount;r.fresh=true;if(j%5===0)accRender();next();}).catch(fail);
    })();
  }
  (function next(){
    if(i>=nodes.length){accRender();phase2();return;}
    var n=nodes[i++];say('Загружаю количество: раздел '+i+' из '+nodes.length+'…');
    ap('/api/acc/nodeamounts',{node:n}).then(function(d){
      todo.forEach(function(r){if(r.node===n&&d.amounts[r.id]!==undefined){r.amount=d.amounts[r.id];r.fresh=true;r.got=true;}});
      accRender();next();}).catch(fail);
  })();
}
function accEdit(r){'''))

res = [patch('funpay_manage.py', FM, 'last_ts'), patch('account_tab.py', AT, 'accLoadAmounts')]
for r, name in zip(res, ('funpay_manage.py', 'account_tab.py')):
    if r:
        shutil.copyfile(r[0], r[0] + '.bak')
        open(r[0], 'w', encoding='utf-8').write(r[1])
        print(f'{name}: готово, копия {name}.bak')
print('Перезапустите программу.')
