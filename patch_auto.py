# -*- coding: utf-8 -*-
"""Правит account_tab.py (рядом с этим файлом), делает копию account_tab.py.bak.
В форме лота с включённой автовыдачей:
  - показывается поле «Товары автовыдачи» (одна строка = один товар);
  - «Количество» блокируется и показывает число строк;
  - в предпросмотре «было → стало» товары не выводятся, только число строк;
  - перед отправкой списка товаров форма перечитывается: если на сайте список уже другой
    (например, часть выдана покупателям), отправка отменяется, чтобы не вернуть выданные товары.
Если какое-то место не найдено ровно один раз, ничего не меняет."""
import os, shutil, sys

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'account_tab.py')
src = open(path, encoding='utf-8').read()
if 'accSync' in src:
    sys.exit('Уже применено.')

E = []

# ---------- Python ----------
E.append((r'''('amount', 'Количество', 'entry'), ('auto', 'Автовыдача', 'check'),
''', r'''('amount', 'Количество', 'entry'), ('auto', 'Автовыдача', 'check'),
             ('secrets', 'Товары автовыдачи', 'text'),
'''))

E.append((r'''def preview(offer, vals):''', r'''fm.ALIASES.setdefault('secrets', r'^secrets$')


def show(n, v):
    # предпросмотр: список товаров автовыдачи не показываем, только число строк
    v = str(v)
    if re.fullmatch(r'secrets', n):
        return f"{len([x for x in v.replace(chr(13), '').split(chr(10)) if x.strip()])} строк"
    return fm.mask(n, v)


def preview(offer, vals):'''))

E.append((r'''    names, sets = set(d['fields']) | set(d['boxes']), []
''', r'''    names, sets = set(d['fields']) | set(d['boxes']), []
    areal = find_name('auto', names)
    auto_on = bool(vals['auto']) if 'auto' in vals else bool(areal and areal in d['fields'])
'''))

E.append((r'''        if not real or alias not in vals:
            continue
        v = vals[alias]
''', r'''        if not real or alias not in vals:
            continue
        if (alias == 'amount' and auto_on) or (alias == 'secrets' and not auto_on):
            continue
        v = vals[alias]
'''))

E.append((r'''            v = str(v).strip() if kind == 'entry' else str(v)
            if v != d['fields'].get(real, ''):
''', r'''            v = str(v).strip() if kind == 'entry' else str(v).replace('\r\n', '\n')
            if v != d['fields'].get(real, '').replace('\r\n', '\n'):
'''))

E.append((r'''    return {'changes': [{'field': n, 'old': fm.mask(n, str(o)), 'new': fm.mask(n, str(w))} for n, o, w in changes],
''', r'''    return {'changes': [{'field': n, 'old': show(n, o), 'new': show(n, w)} for n, o, w in changes],
'''))

E.append((r'''    S['pending'] = None
    status, resp = fm.submit_form(''', r'''    S['pending'] = None
    sk = find_name('secrets', set(d['fields']) | set(d['boxes']))
    if sk and any(c[0] == sk for c in p['changes']):
        _, _, fresh_html = fm.request(d['page'], S['key'])
        fresh = BeautifulSoup(fresh_html, 'html.parser')
        fform = fresh.find('form', class_=re.compile('offer|edit', re.I)) or fresh.find('form')
        if not fform:
            raise fm.Stop('Не смог перепроверить список товаров перед отправкой. Ничего не отправлено.')
        now = fm.form_fields(fform)[0].get(sk, '').replace('\r\n', '\n')
        if now != d['fields'].get(sk, '').replace('\r\n', '\n'):
            raise fm.Stop('Список товаров на сайте изменился с момента открытия формы (возможно, часть уже выдана покупателям). Ничего не отправлено, откройте лот заново.')
    status, resp = fm.submit_form('''))

# ---------- JS ----------
E.append((r'''var p=$('ac-edit'),W={};p.textContent='';''', r'''var p=$('ac-edit'),W={},E={};p.textContent='';'''))

E.append((r'''p.appendChild(lb);W[f.alias]=function(){return c.checked;};return;}''',
          r'''p.appendChild(lb);W[f.alias]=function(){return c.checked;};E[f.alias]={inp:c};return;}'''))

E.append((r'''    p.appendChild(el('div','fh',f.label));
    if(f.kind==='text'){w=el('textarea');w.rows=8;}else{w=el('input');w.type='text';}
''', r'''    var fh=el('div','fh',f.label);p.appendChild(fh);
    if(f.kind==='text'){w=el('textarea');w.rows=(f.alias==='secrets'?12:8);}else{w=el('input');w.type='text';}
'''))

E.append((r'''p.appendChild(w);W[f.alias]=function(){return w.value;};});
''', r'''p.appendChild(w);W[f.alias]=function(){return w.value;};E[f.alias]={inp:w,fh:fh};});
  accSync(E);
'''))

E.append((r'''d.fields.forEach(function(f){if(f.alias==='amount'&&f.value!=='')r.amount=String(f.value);});''',
          r'''accAmt(r,d.fields);'''))

E.append((r'''d.fields.forEach(function(f){if(f.alias==='amount')r.amount=String(f.value);});''',
          r'''accAmt(r,d.fields);'''))

E.append((r'''function accEdit(r){''', r'''function accLines(t){return String(t||'').split(/\r?\n/).filter(function(x){return x.trim();}).length;}
function accAmt(r,fields){
  var on=false,sec=null,am=null;
  fields.forEach(function(f){
    if(f.alias==='auto')on=!!f.value;
    if(f.alias==='secrets')sec=f.value;
    if(f.alias==='amount')am=f.value;});
  if(on&&sec!==null)r.amount=String(accLines(sec));
  else if(am!==null&&am!=='')r.amount=String(am);
}
function accSync(E){
  var a=E.auto,s=E.secrets,m=E.amount;
  function upd(){
    var on=!!(a&&a.inp.checked);
    if(s){
      if(!s.hint){
        s.hint=el('div','cnt','Одна строка — один товар. Выдаются сверху вниз, выданные удаляются. Используйте \\n для переноса внутри товара.');
        s.inp.parentNode.insertBefore(s.hint,s.inp.nextSibling);}
      s.inp.style.display=on?'':'none';s.fh.style.display=on?'':'none';s.hint.style.display=on?'':'none';}
    if(m&&s){
      m.inp.disabled=on;
      if(on)m.inp.value=String(accLines(s.inp.value));}
  }
  if(a)a.inp.addEventListener('change',upd);
  if(s)s.inp.addEventListener('input',upd);
  upd();
}
function accEdit(r){'''))

for old, new in E:
    if src.count(old) != 1:
        sys.exit(f'СТОП: не нашёл ровно одно место: {old[:70]!r}. Файл не изменён. Пришлите мне этот вывод.')
    src = src.replace(old, new, 1)
shutil.copyfile(path, path + '.bak')
open(path, 'w', encoding='utf-8').write(src)
print('Готово. Копия: account_tab.py.bak. Перезапустите программу.')
