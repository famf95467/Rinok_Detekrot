/* ---------- Данные ---------- */
function stamp(p){var t=p.time?p.time.replace('T',' '):'';return t||p.date||'';}
function showFetch(f){var lg=$('d-log'),t=(f.running?'Идёт загрузка'+(f.source==='авто'?' (автоснимок)':'')+'… ':'')+(f.text||'');lg.textContent=(t?t+'\n\n':'')+(f.log||'');lg.style.display=(t||f.log)?'block':'none';}
function renderSnaps(list){
  var box=$('d-snaps');box.textContent='';
  if(!list.length){box.appendChild(el('div','empty','Сохранённых страниц нет. Нажмите «Обновить» или сохраните страницу в папку pages.'));return;}
  var t=el('table'),hr=el('tr'),th=el('thead');
  ['Дата и время','Файл','Лотов на странице (факт)','В расчёте (оценка)','Валюта (факт)','В истории'].forEach(function(h,i){hr.appendChild(el('th',(i>1&&i<4)?'num':'',h));});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  list.forEach(function(x){var tr=el('tr');tr.appendChild(el('td','',x.date+(x.time?' '+x.time:'')));tr.appendChild(el('td','',x.file));
    tr.appendChild(el('td','num',x.error?'—':String(x.total)));tr.appendChild(el('td','num',(x.error||x.calc==='')?'—':String(x.calc)));
    tr.appendChild(el('td',x.not_rub?'warn':'',x.error?'—':(x.units+(x.not_rub?' (не только рубли)':''))));
    tr.appendChild(el('td',x.error?'warn':'',x.error?('ошибка: '+x.error):(x.page_exists?'да':'да (файл страницы удалён, история сохранена)')));tb.appendChild(tr);});
  t.appendChild(tb);fold5(box,'d-snaps',t);
}
function renderData(d){
  $('d-note').textContent='';var p=d.protection,st=$('d-state');
  if(p.stopped){st.className='state bad';st.textContent='Остановлено: '+(p.reason||p.result)+', '+stamp(p)+'. Повтор сегодня запрещён, попробуйте завтра.'+(p.stop_file?' Ответ сайта сохранён в папке pages (файл _stop_...).':'');}
  else{st.className='state ok';st.textContent='Можно обновлять.'+(d.has_today?' Снимок за сегодня уже есть.':' Снимка за сегодня ещё нет.');}
  $('d-last').textContent=p.result?('Последний запуск загрузчика: '+p.result+', '+stamp(p)+'.'):'Запусков загрузчика ещё не было.';
  $('d-fetch').disabled=!!(p.stopped||d.fetch.running||!d.can_fetch);
  if(!d.can_fetch)$('d-note').textContent='Не найден загрузчик, кнопка «Обновить» отключена.';
  renderSnaps(d.snapshots);if(d.fetch.running)poll();
}
function loadAuto(){
  return api('/api/auto').then(function(a){
    $('a-on').checked=a.enabled;$('a-h').value=a.hours;$('a-state').textContent=a.text;var box=$('a-log');box.textContent='';
    if(!a.log.length)return;
    fold5(box,'a-log',tbl(['Начало запуска','Кто запустил','Результат'],a.log.map(function(r){return[r.time,r.source,r.text];})));
  }).catch(function(e){say(e.message,true);});
}
function loadData(){$('d-note').textContent='Читаю снимки… при первом запуске может занять до минуты.';loadAuto();loadBackups();return api('/api/data').then(renderData).catch(function(e){$('d-note').textContent='';say(e.message,true);});}
function loadBackups(){return api('/api/backups').then(function(d){
  var box=$('bk-list');box.textContent='';
  $('bk-state').textContent=d.items.length?('Копий на сервере: '+d.items.length+'.'):'Копий на сервере пока нет: первая сделается сама в течение часа после запуска.';
  d.items.forEach(function(x){
    var row=el('div','cnt'),a=el('a','',x.name);a.href='/api/backup_get?name='+encodeURIComponent(x.name);
    row.appendChild(a);row.appendChild(document.createTextNode(' — '+x.time.replace('T',' ')+', '+(x.size/1048576).toFixed(1)+' МБ'));box.appendChild(row);});
}).catch(function(e){say(e.message,true);});}
$('bk-dl').addEventListener('click',function(){location.href='/api/export_zip';});
$('bk-dlp').addEventListener('click',function(){location.href='/api/export_zip?pages=1';});
$('bk-now').addEventListener('click',function(){
  api('/api/backups/make',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(){say('Копия сделана.');return loadBackups();}).catch(function(e){say(e.message,true);});});
$('a-save').addEventListener('click',function(){ap('/api/auto',{enabled:$('a-on').checked,hours:Number($('a-h').value)}).then(function(){say('');loadAuto();}).catch(function(e){say(e.message,true);});});
function poll(){clearTimeout(pollT);api('/api/fetch').then(function(f){showFetch(f);if(f.running)pollT=setTimeout(poll,1500);else loadData().then(function(){return load('');});}).catch(function(e){say(e.message,true);});}
$('d-fetch').addEventListener('click',function(){
  if(!confirm('Сделать один запрос страницы категории на FunPay (как гость)?'))return;
  $('d-fetch').disabled=true;ap('/api/fetch').then(function(){say('');poll();}).catch(function(e){say(e.message,true);loadData();});
});

