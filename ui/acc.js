/* ---------- Аккаунт ---------- */
var AC={rows:[],rs:{},logged:false};
function loadAcc(){
  loadSec();
  return api('/api/acc/status').then(function(s){
    AC.logged=s.logged;
    $('ac-login').style.display=s.logged?'none':'block';$('ac-main').style.display=s.logged?'block':'none';
    $('ac-file').style.display=s.keyfile?'inline-block':'none';$('ac-forget').style.display=(s.keyfile&&!s.cloud)?'inline-block':'none';if(s.cloud&&$('quit'))$('quit').style.display='none';if(s.cloud&&$('im-box'))$('im-box').style.display='block';
    if(s.locked)say('Сессия аккаунта остановлена: сайт ответил блокировкой или проверкой. Запросы отключены до перезапуска программы.',true);
    if(!s.logged)return;
    $('ac-nick').textContent=s.nick;$('ac-id').textContent='ID: '+s.uid;
    var im=$('ac-ava');if(s.avatar){im.src=s.avatar;im.style.display='inline-block';}else im.style.display='none';
    if(!AC.rows.length)accOffers();
  }).catch(function(e){say(e.message,true);});
}
function loadSec(){
  return api('/api/security').then(function(d){
    var b=$('sec-box');b.style.display=d.cloud?'block':'none';if(!d.cloud)return;
    $('sec-note').textContent='Пароль проверяется на каждый запрос. '+d.limits+' Блокировка снимается сама или перезапуском сервиса. Пароли в журнал не пишутся.';
    var k=d.key;$('sec-key').textContent='golden_key: '+(k.bad?'НЕ РАБОТАЕТ ('+k.bad+')':(k.logged?'принят сайтом, вход выполнен':(k.env?'задан в переменной, вход ещё не выполнен':'не задан')))+(k.locked?'. Сессия аккаунта остановлена сайтом.':'.');
    $('sec-key').style.color=k.bad?'var(--x)':'';
    $('sec-locked').textContent=d.locked.length?('Сейчас заблокированы: '+d.locked.map(function(x){return x.ip+' (ещё '+x.min+' мин)';}).join(', ')+'.'):'';
    var lg=$('sec-log');lg.textContent='';
    if(d.events.length)fold5(lg,'sec-log',tbl(['Время','IP','Событие','Примечание'],d.events.map(function(x){return [x.time,x.ip,x.event,x.note];})));else lg.appendChild(el('div','cnt','Событий пока нет.'));
  }).catch(function(e){say(e.message,true);});
}
$('sec-ack').addEventListener('click',function(){ap('/api/security/ack').then(function(){loadSec();return api('/api/autopilot/status').then(apBanner);}).catch(function(e){say(e.message,true);});});
$('sec-reload').addEventListener('click',loadSec);
function accLogin(useFile){
  var k=$('ac-key').value.trim();if(!useFile&&!k){say('Вставьте golden_key.',true);return;}
  say('Вхожу…');
  ap('/api/acc/login',{key:useFile?'':k,use_file:useFile,remember:$('ac-rem').checked}).then(function(){$('ac-key').value='';say('');AC.rows=[];loadAcc();}).catch(function(e){say(e.message,true);});
}
function accOffers(){say('Загружаю лоты…');return ap('/api/acc/offers').then(function(d){AC.rows=d.rows;accRender();say('');}).catch(function(e){say(e.message,true);});}
function accRender(){
  var q=$('ac-q').value.trim().toLowerCase(),box=$('ac-tbl');box.textContent='';
  var rows=AC.rows.filter(function(r){return !q||(r.title+' '+r.section).toLowerCase().indexOf(q)>=0;});
  $('ac-sum').textContent='Ваших лотов: '+AC.rows.length+(q?', показано '+rows.length:'')+'. Количество берётся из формы лота, пока не загружено, показывается как на странице профиля.';
  var t=el('table'),th=el('thead'),hr=el('tr');
  ['','ID','Раздел','Название','Автовыдача','Цена','Кол-во'].forEach(function(h,i){hr.appendChild(el('th',i>=5?'num':'',h));});th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  rows.forEach(function(r){
    var tr=el('tr'),td=el('td','btns'),b=el('button','b','Изменить');b.type='button';b.addEventListener('click',function(){accEdit(r);});td.appendChild(b);tr.appendChild(td);
    tr.appendChild(el('td','id',r.id));tr.appendChild(el('td','',r.section));tr.appendChild(el('td','',r.title));tr.appendChild(el('td','',r.auto==='да'?'да':'нет'));
    tr.appendChild(el('td','num',r.price));tr.appendChild(el('td','num',r.amount||'нет на странице'));tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(foldWrap('ac-tbl','Ваши лоты',rows.length,t));if(!rows.length)box.appendChild(el('div','empty','Лотов нет.'));raiseRender();
}
function raiseSections(){var m={},ord=[];AC.rows.forEach(function(r){if(!r.node)return;if(!m[r.node]){m[r.node]={node:r.node,section:r.section,n:0};ord.push(m[r.node]);}m[r.node].n++;});return ord;}
function raiseRender(){
  var box=$('ac-rlist');box.textContent='';var list=raiseSections();
  if(!list.length){box.appendChild(el('div','cnt','Разделов нет: список лотов ещё не загружен.'));return;}
  var t=el('table'),th=el('thead'),hr=el('tr');['','Раздел','Лотов','Ответ сайта'].forEach(function(h,i){hr.appendChild(el('th',i===2?'num':'',h));});th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  list.forEach(function(x){var tr=el('tr'),td=el('td','btns'),b=el('button','b','Поднять');b.type='button';
    b.addEventListener('click',function(){if(!confirm('Поднять предложения раздела «'+x.section+'»?'))return;b.disabled=true;raiseOne(x).catch(function(e){say(e.message,true);}).then(function(){b.disabled=false;});});
    td.appendChild(b);tr.appendChild(td);tr.appendChild(el('td','',x.section));tr.appendChild(el('td','num',String(x.n)));tr.appendChild(el('td','',AC.rs[x.node]||''));tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(foldWrap('ac-rlist','Разделы для поднятия',list.length,t));
}
function raiseOne(x){
  say('Поднимаю: '+x.section+'…');
  return ap('/api/acc/raise',{node:x.node}).then(function(d){AC.rs[x.node]=new Date().toLocaleTimeString('ru-RU')+': '+(d.msg||'(пустой ответ)');say('');raiseRender();return d;});
}
function raiseAll(){
  var list=raiseSections();if(!list.length){say('Сначала загрузите список лотов.');return;}
  if(!confirm('Поднять предложения в '+list.length+' разделах? Запросы идут по одному с паузой. При ошибке остановлюсь.'))return;
  $('ac-raiseall').disabled=true;var i=0;
  (function next(){if(i>=list.length){$('ac-raiseall').disabled=false;say('Готово: прошли все разделы. Ответы сайта в таблице.');return;}
    raiseOne(list[i++]).then(next).catch(function(e){$('ac-raiseall').disabled=false;say(e.message,true);});})();
}
function accAmounts(){
  var nodes=raiseSections();if(!nodes.length){say('Сначала загрузите список лотов.');return;}
  if(!confirm('Будет по одному запросу на раздел ('+nodes.length+'), с паузами. Продолжить?'))return;
  $('ac-amt').disabled=true;var i=0;
  (function next(){
    if(i>=nodes.length){$('ac-amt').disabled=false;say('Готово: количество загружено.');accRender();return;}
    var x=nodes[i++];say('Загружаю количество: '+i+' из '+nodes.length+'…');
    ap('/api/acc/nodeamounts',{node:x.node}).then(function(d){
      AC.rows.forEach(function(r){if(d.amounts&&d.amounts[r.id]!==undefined)r.amount=String(d.amounts[r.id]);});accRender();next();
    }).catch(function(e){$('ac-amt').disabled=false;say(e.message,true);});
  })();
}
function accEdit(r){
  say('Загружаю форму лота…');
  ap('/api/acc/form',{node:r.node,id:r.id}).then(function(d){say('');d.fields.forEach(function(f){if(f.alias==='amount'&&f.value!=='')r.amount=String(f.value);});accRender();accForm(r,d.fields);}).catch(function(e){say(e.message,true);});
}
function accForm(r,fields){
  var p=$('ac-edit'),W={};p.textContent='';p.style.display='block';p.appendChild(el('h3','','Лот '+r.id));p.firstChild.style.marginTop='0';
  if(!fields.length)p.appendChild(el('div','cnt','Поля формы не распознаны. Ничего не отправлено.'));
  fields.forEach(function(f){
    if(f.kind==='check'){var lb=el('label'),c=el('input');c.type='checkbox';c.checked=!!f.value;lb.appendChild(c);lb.appendChild(el('span','',' '+f.label));lb.style.display='block';p.appendChild(lb);W[f.alias]=function(){return c.checked;};return;}
    p.appendChild(el('div','fh',f.label));var w;
    if(f.kind==='text'){w=el('textarea');w.rows=f.alias==='secrets'?6:8;}else{w=el('input');w.type='text';}
    w.value=f.value;w.className='full';p.appendChild(w);W[f.alias]=function(){return w.value;};});
  var conf=el('div'),bar=el('div','bar'),pv=el('button','','Проверить изменения'),cl=el('button','','Закрыть');pv.type=cl.type='button';
  cl.addEventListener('click',function(){p.style.display='none';});
  pv.addEventListener('click',function(){var v={};Object.keys(W).forEach(function(k){v[k]=W[k]();});
    ap('/api/acc/preview',{id:r.id,values:v}).then(function(d){say('');accConfirm(conf,r,d);}).catch(function(e){say(e.message,true);});});
  bar.appendChild(pv);bar.appendChild(cl);p.appendChild(bar);p.appendChild(conf);p.scrollIntoView({behavior:'smooth'});
}
function accConfirm(box,r,d){
  box.textContent='';
  if(!d.changes.length){box.appendChild(el('div','cnt','Вы ничего не изменили, отправлять нечего.'));return;}
  box.appendChild(el('h3','','Было → стало (пока ничего не отправлено)'));
  box.appendChild(tbl(['Поле','Было','Стало'],d.changes.map(function(c){return[c.field,c.old,c.new];})));
  var bar=el('div','bar'),go=el('button','','Отправить на FunPay');go.type='button';bar.appendChild(go);box.appendChild(bar);
  go.addEventListener('click',function(){
    if(!confirm('Отправить эти изменения в лот '+r.id+' на FunPay?'))return;go.disabled=true;
    ap('/api/acc/apply',{id:r.id,token:d.token}).then(function(x){box.textContent='';
      box.appendChild(el('div','state ok','Ответ сайта: HTTP '+x.status+'. Программа не толкует ответ, проверьте лот на сайте.'));box.appendChild(el('pre','log',x.resp||''));
      AC.rows=[];accOffers();}).catch(function(e){say(e.message,true);go.disabled=false;});});
}
$('ac-btn').addEventListener('click',function(){accLogin(false);});$('ac-file').addEventListener('click',function(){accLogin(true);});
$('ac-forget').addEventListener('click',function(){if(!confirm('Удалить golden_key.txt с этого ПК?'))return;ap('/api/acc/forget').then(loadAcc).catch(function(e){say(e.message,true);});});
$('ac-amt').addEventListener('click',accAmounts);$('ac-raiseall').addEventListener('click',raiseAll);$('ac-reload').addEventListener('click',accOffers);$('ac-q').addEventListener('input',accRender);
$('ac-out').addEventListener('click',function(){ap('/api/acc/logout').then(function(){AC.rows=[];$('ac-edit').style.display='none';loadAcc();say('Вы вышли, ключ стёрт из памяти программы.');});});

