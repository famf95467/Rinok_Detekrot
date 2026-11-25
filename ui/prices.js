/* ---------- Цены ---------- */
var S={mode:'lots',sort:{lots:{col:'price',dir:1},sellers:{col:'min',dir:1}}};
var LOTCOLS=[{k:'price',t:'Цена',num:1,s:1},{k:'seller',t:'Продавец',s:1},{k:'reviews',t:'Отзывов у продавца',num:1,s:1},{k:'title',t:'Название',s:1},{k:'term',t:'Срок'},{k:'auto_issue',t:'Автовыдача'},{k:'tags',t:'Пометки'}];
var SELCOLS=[{k:'seller',t:'Продавец',s:1},{k:'n',t:'Лотов',num:1,s:1},{k:'min',t:'Мин. цена',num:1,s:1},{k:'max',t:'Макс. цена',num:1,s:1},{k:'reviews',t:'Отзывов',num:1,s:1}];
var PF=FP($('p-filters'),function(){return pdata?pdata.lots:[];},function(){recalc();});
function bySeller(rows){var m={},out=[];rows.forEach(function(l){var s=m[l.seller];if(!s){s=m[l.seller]={seller:l.seller,n:0,min:l.price,max:l.price,reviews:l.reviews};out.push(s);}s.n++;if(l.price<s.min)s.min=l.price;if(l.price>s.max)s.max=l.price;});return out;}
function sortRows(rows){var cur=S.sort[S.mode],tie=S.mode==='lots'?'price':'min';return rows.slice().sort(function(a,b){var x=a[cur.col],y=b[cur.col],r=(typeof x==='string')?x.localeCompare(y,'ru'):(x-y);if(r===0)r=a[tie]-b[tie];return r*cur.dir;});}
function renderTable(rows){
  var box=$('p-table');box.textContent='';var cols=S.mode==='lots'?LOTCOLS:SELCOLS,cur=S.sort[S.mode];
  var d=sortRows(S.mode==='lots'?rows:bySeller(rows)),t=el('table'),hr=el('tr'),th=el('thead');
  cols.forEach(function(c){var h=el('th',(c.num?'num':'')+(c.s?' srt':''),c.t+(cur.col===c.k?(cur.dir>0?' ▲':' ▼'):''));
    if(c.s)h.addEventListener('click',function(){S.sort[S.mode]={col:c.k,dir:(cur.col===c.k?-cur.dir:1)};recalc();});hr.appendChild(h);});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody'),shown=d.slice(0,1000);
  shown.forEach(function(r){var tr=el('tr');
    if(S.mode==='lots'){tr.appendChild(el('td','num',money(r.price)+' ₽'));tr.appendChild(el('td','',r.seller));tr.appendChild(el('td','num',String(r.reviews)));tr.appendChild(el('td','',r.title));tr.appendChild(el('td','',r.term));tr.appendChild(el('td','',r.auto_issue==='да'?'да':'нет'));
      var tg=el('td','');if(r.dup)tg.appendChild(el('span','tag','дубль '+r.dup));if(r.niche)tg.appendChild(el('span','tag','ниша'));tr.appendChild(tg);}
    else{tr.appendChild(el('td','',r.seller));tr.appendChild(el('td','num',String(r.n)));tr.appendChild(el('td','num',money(r.min)+' ₽'));tr.appendChild(el('td','num',money(r.max)+' ₽'));tr.appendChild(el('td','num',String(r.reviews)));}
    tb.appendChild(tr);});
  t.appendChild(tb);fold5(box,'p-table-'+S.mode,t,d.length,1000);
  if(d.length>shown.length)box.appendChild(el('div','empty','Показаны первые 1000 из '+d.length+'. Уточните фильтры.'));
}
function recalc(){
  if(!pdata)return;var e=$('p-empty'),box=$('p-table');
  if(pdata.note){e.textContent=pdata.note;e.style.display='block';box.textContent='';return;}
  var rows=PF.apply(pdata.lots),st=stats(rows.map(function(l){return l.price;})),sl={};rows.forEach(function(l){sl[l.seller]=1;});
  $('s-n').textContent=String(rows.length);$('s-sellers').textContent=String(Object.keys(sl).length);
  $('s-min').textContent=st?money(st.min)+' ₽':'—';$('s-max').textContent=st?money(st.max)+' ₽':'—';$('s-med').textContent=st?money(st.med)+' ₽':'—';
  var mb=$('p-more');mb.textContent='';
  mb.appendChild(el('div','','Q1: '+(st&&st.q1!==null?money(st.q1)+' ₽':'мало данных (нужно не меньше 5 цен)')));
  mb.appendChild(el('div','','Q3: '+(st&&st.q3!==null?money(st.q3)+' ₽':'мало данных (нужно не меньше 5 цен)')));
  mb.appendChild(el('div','','Без фильтров в расчёте: '+pdata.kept+' лотов от '+pdata.sellers+' продавцов.'));
  $('p-fact').textContent='Страница '+(pdata.date||'без даты')+': лотов на странице '+pdata.total+'. Показано '+rows.length+' из '+pdata.kept+'. Цены в рублях, это цены витрины, а не сделки.';
  if(!rows.length){e.textContent=pdata.kept?'По этим фильтрам лотов нет.':'В расчёт не попало ни одного лота. Отметьте лоты на экране «Отметки».';e.style.display='block';box.textContent='';return;}
  e.style.display='none';renderTable(rows);
}
function loadPrices(){
  var s=$('snap').value;
  return api('/api/prices'+(s?'?snap='+encodeURIComponent(s):'')).then(function(d){
    pdata=d;var have={};d.lots.forEach(function(l){have[l.seller]=1;});PF.prune(have);
    $('p-est').textContent='Что считать скриптом, решают правила и ваши отметки. В расчёте: правилом '+d.by_rule+', вручную '+d.by_hand+' (из них ниша '+d.niche+'). Ждут отметки и в цены не вошли: '+d.unc_open+'.';
    PF.list();recalc();say('');}).catch(function(e){say(e.message,true);});
}
function setMode(m){S.mode=m;$('m-lots').className='seg'+(m==='lots'?' cur':'');$('m-sellers').className='seg'+(m==='sellers'?' cur':'');recalc();}
$('m-lots').addEventListener('click',function(){setMode('lots');});$('m-sellers').addEventListener('click',function(){setMode('sellers');});

