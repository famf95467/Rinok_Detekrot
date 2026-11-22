/* ---------- Шпион ---------- */
/* Запускает фоновую задачу на сервере (/api/spy/*) и показывает продавцов с отзывами по товару, лучшие первыми. Ничего не пишет на сайт. */
var SP={res:null,timer:null,busy:false,filled:false};
function spUrl(p){return 'https://funpay.com'+p;}
function spLink(path,text,cls){var a=el('a',cls||'ol',text);a.href=spUrl(path);a.target='_blank';a.rel='noopener noreferrer';return a;}
function spFill(res){
  /* Один раз за открытие страницы, пока пользователь ничего не вводил: иначе стёртые поля возвращались бы после каждого опроса статуса. */
  if(SP.filled||!res||!res.params)return;SP.filled=true;var p=res.params;
  function set(id,v){var e=$(id);if(e&&!e.value&&v!==null&&v!==undefined&&v!=='')e.value=v;}
  set('spy-cat',p.node);set('spy-q',p.query);set('spy-ex',p.exclude);set('spy-key',p.review_key);set('spy-pmin',p.price_min);if(p.sort)$('spy-order').value=p.sort;set('spy-lots',p.lots_limit);set('spy-pmax',p.price_max);
}
function spBody(){
  return {category:$('spy-cat').value,query:$('spy-q').value,exclude:$('spy-ex').value,review_key:$('spy-key').value,
    sort:$('spy-order').value,lots_limit:$('spy-lots').value,price_min:$('spy-pmin').value,price_max:$('spy-pmax').value,max_sellers:$('spy-ms').value,review_pages:Number($('spy-pg').value)};
}
function spSorted(rows){
  var m=$('spy-sort').value,a=rows.slice();
  if(!$('spy-zero').checked)a=a.filter(function(x){return x.n>0;});
  function minp(x){return x.lots.length?x.lots[0].price:1e18;}
  if(m==='n')a.sort(function(x,y){return y.n-x.n||(y.score||0)-(x.score||0);});
  else if(m==='avg')a.sort(function(x,y){return (y.avg||0)-(x.avg||0)||y.n-x.n;});
  else if(m==='price')a.sort(function(x,y){return minp(x)-minp(y);});
  return a;
}
function spCards(r){
  var box=$('spy-cards');box.textContent='';
  if(!r){return;}
  [['Лотов в категории',r.lots_total],['Подходит под запрос',r.lots_matched],['Взято в работу',r.lots_used===undefined?r.lots_matched:r.lots_used],['Продавцов с такими лотами',r.sellers_total],['Проверено профилей',r.sellers_checked]].forEach(function(c){
    var d=el('div','sc');d.appendChild(el('div','sl',c[0]));d.appendChild(el('div','sv',String(c[1])));box.appendChild(d);});
}
function spList(){
  var box=$('spy-list'),r=SP.res;box.textContent='';
  $('spy-sbar').style.display=r&&r.sellers&&r.sellers.length?'flex':'none';
  if(!r)return;
  var rows=spSorted(r.sellers||[]);
  if(!rows.length){box.appendChild(el('div','empty',r.sellers&&r.sellers.length?'Нет продавцов с отзывами по этому слову. Включите показ продавцов без отзывов или смените слово в отзывах.':'Продавцов не найдено.'));return;}
  var t=el('table'),th=el('thead'),hr=el('tr');
  [['№',1],['Продавец',0],['Балл (о)',1],['Отзывов на товар',1],['Средняя',1],['5★',1],['1–2★',1],['Последний',0],['Лоты (цена, ссылка)',0]].forEach(function(c){hr.appendChild(el('th',c[1]?'num':'',c[0]));});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  rows.forEach(function(x,i){
    var tr=el('tr');tr.appendChild(el('td','num',String(i+1)));
    var tn=el('td');tn.appendChild(spLink(x.profile,x.name||('#'+x.uid)));
    var meta=[];if(x.cached)meta.push('из кэша');if(x.pages>1)meta.push('страниц отзывов '+x.pages);meta.push('просмотрено отзывов '+x.seen);
    tn.appendChild(el('div','cnt',meta.join(', ')));
    if(x.quotes&&x.quotes.length){var d=el('details','more'),s=el('summary','','Что пишут покупатели');d.appendChild(s);
      x.quotes.forEach(function(q){d.appendChild(el('div','cnt',(q.rating?q.rating+'★ ':'')+'«'+q.text+'»'));});tn.appendChild(d);}
    tr.appendChild(tn);
    tr.appendChild(el('td','num',x.score===null?'—':String(x.score).replace('.',',')));
    tr.appendChild(el('td','num',String(x.n)));
    tr.appendChild(el('td','num',x.avg===null?'—':x.avg.toFixed(2).replace('.',',')));
    tr.appendChild(el('td','num',x.five_share===null?'—':Math.round(x.five_share*100)+' %'));
    tr.appendChild(el('td','num',String(x.bad)));
    tr.appendChild(el('td','',x.last||'—'));
    var tl=el('td');
    x.lots.forEach(function(l){var d=el('div');d.appendChild(document.createTextNode(money(l.price)+' ₽ · '));d.appendChild(spLink(l.url,l.title.length>70?l.title.slice(0,70)+'…':l.title));if(l.auto)d.appendChild(el('span','tag','автовыдача'));tl.appendChild(d);});
    tr.appendChild(tl);tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(t);
}
function spRender(st){
  var s=$('spy-state');
  var txt=st.running?(st.stage||'Работаю')+(st.total?': '+st.done+' из '+st.total:''):'';
  if(st.stopped){s.className='state bad';s.textContent='Запросы остановлены: '+st.stopped+'. Ничего не обходится, повтор завтра.';s.style.display='block';}
  else if(st.err){s.className='state bad';s.textContent='Сбой: '+st.err;s.style.display='block';}
  else s.style.display='none';
  $('spy-prog').textContent=txt||(st.ended?'Последний запуск: '+st.ended.replace('T',' '):'');
  $('spy-go').disabled=!!st.running;$('spy-stop').style.display=st.running?'inline-block':'none';
  $('spy-log').textContent=(st.log||[]).join('\n');
  var n=$('spy-notes');n.textContent='';
  if(st.result){SP.res=st.result;spFill(st.result);spCards(st.result);
    (st.result.notes||[]).forEach(function(x){var d=el('div','msg bad',x);d.style.display='block';n.appendChild(d);});
    $('spy-csv').style.display=(st.result.sellers&&st.result.sellers.length)?'inline-block':'none';
    spList();}
}
function spPoll(){
  clearTimeout(SP.timer);
  return api('/api/spy/status').then(function(st){
    spRender(st);
    if(st.running&&view==='spy')SP.timer=setTimeout(spPoll,1500);
  }).catch(function(e){say(e.message,true);});
}
function spyLoad(){return spPoll();}
$('spy-go').addEventListener('click',function(){
  SP.filled=true;
  var b=spBody(),n=Math.max(1,Math.min(40,Number(b.max_sellers)||15));
  if(!confirm('Запустить шпиона? Будет 1 запрос страницы категории и до '+n+' запросов профилей продавцов'+(b.review_pages>1?' (плюс подгрузка отзывов)':'')+', с паузами 2,5–5 с, как гость. Профили из кэша (до 6 ч) не запрашиваются.'))return;
  say('');
  ap('/api/spy/start',b).then(function(){return spPoll();}).catch(function(e){say(e.message,true);});
});
$('spy-stop').addEventListener('click',function(){ap('/api/spy/stop').then(function(){say('Останавливаю после текущего запроса…');}).catch(function(e){say(e.message,true);});});
$('spy-csv').addEventListener('click',function(){ap('/api/spy/export').then(function(r){say('Таблица сохранена: '+r.path+' (строк '+r.rows+').');}).catch(function(e){say(e.message,true);});});
$('spy-sort').addEventListener('change',spList);$('spy-zero').addEventListener('change',spList);
