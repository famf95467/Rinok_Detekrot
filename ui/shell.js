<script>
(function(){
'use strict';
var TABS=[['home','Главная'],['marks','Отметки'],['prices','Цены'],['data','Данные'],['hist','История'],['acc','Аккаунт'],['chat','Сообщения'],['remind','Напоминания'],['confirm','Подтверждения'],['review','Отзывы'],['auto','Автопилот'],['stats','Статистика'],['sales','Продажи'],['spy','Шпион'],['merge','Слияние лотов'],['plugins','Плагины']];
var MARKS=['скрипт','ниша','нет'],CLS={'скрипт':'s','ниша':'n','нет':'x'};
var lots=[],filter='none',data={},view='home',pdata=null,pollT=null;
function $(id){return document.getElementById(id);}
function say(t,bad){var b=$('msg');b.textContent=t||'';b.className='msg'+(bad?' bad':'');b.style.display=t?'block':'none';}
function api(url,opts){return fetch(url,opts).then(function(r){return r.json().catch(function(){return {};}).then(function(j){if(!r.ok)throw new Error(j.error||('Ошибка '+r.status));return j;});},function(){throw new Error('Программа не отвечает. Проверьте, что чёрное окно не закрыто.');});}
document.addEventListener('click',function(e){if(!e.target||e.target.id!=='im-go')return;var f=$('im-file').files[0],r=$('im-res');if(!f){r.textContent='Выберите zip-файл.';return;}if(!confirm('Загрузить '+f.name+' и заменить совпадающие файлы данных?'))return;r.textContent='Загрузка…';fetch('/api/import_zip',{method:'POST',headers:{'Content-Type':'application/zip'},body:f}).then(function(x){return x.json();}).then(function(j){r.textContent=j.error?('Ошибка: '+j.error):('Готово: файлов '+j.files+', пропущено '+j.skipped+(j.skipped_sample&&j.skipped_sample.length?' ('+j.skipped_sample.join(', ')+')':'')+'. Теперь перезапустите сервис в Railway.');}).catch(function(x){r.textContent='Ошибка: '+x.message;});});
function ap(u,b){return api(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
var CATH={};
function catHint(id){var inp=$(id);if(!inp||CATH[id])return;var h=el('div','cnt');h.style.minHeight='1.3em';inp.parentNode.appendChild(h);var t=null,seq=0;
  function upd(){clearTimeout(t);var v=String(inp.value||'').trim(),my=++seq;if(!v){h.textContent='';h.className='cnt';return;}h.textContent='Ищу название…';h.className='cnt';
    t=setTimeout(function(){api('/api/spy/catname?node='+encodeURIComponent(v)).then(function(d){if(my!==seq)return;h.textContent=d.found===true&&d.name?d.name:(d.note||'');h.className='cnt'+(d.found===false?' warn':'');}).catch(function(e){if(my!==seq)return;h.textContent='Название не проверено: '+e.message;h.className='cnt';});},700);}
  inp.addEventListener('input',upd);CATH[id]=upd;}
function catRefresh(id){if(CATH[id])CATH[id]();}
function numOrNull(v){var x=parseFloat(String(v).replace(',','.'));return isNaN(x)?null:x;}
function money(v){return(v===null||v===undefined||v==='')?'—':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:2});}
function qinc(a,i){var m=a.length-1,j=Math.floor(i*m/4),d=i*m-j*4;return j+1<a.length?(a[j]*(4-d)+a[j+1]*d)/4:a[j];}
function stats(v){if(!v.length)return null;var a=v.slice().sort(function(x,y){return x-y;}),n=a.length,m=n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2;return{n:n,min:a[0],max:a[n-1],med:m,q1:n>=5?qinc(a,1):null,q3:n>=5?qinc(a,3):null};}
function ordLink(id){var a=el('a','ol','#'+id);a.href='https://funpay.com/orders/'+encodeURIComponent(id)+'/';a.target='_blank';a.rel='noopener noreferrer';a.title='Открыть страницу заказа на FunPay';return a;}
function tbl(cols,rows,nc){var t=el('table'),th=el('thead'),hr=el('tr');cols.forEach(function(c,i){hr.appendChild(el('th',nc&&nc.indexOf(i)>=0?'num':'',c));});th.appendChild(hr);t.appendChild(th);var tb=el('tbody');rows.forEach(function(r){var tr=el('tr');r.forEach(function(v,i){tr.appendChild(el('td',nc&&nc.indexOf(i)>=0?'num':'',v));});tb.appendChild(tr);});t.appendChild(tb);return t;}
function lsGet(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function lsSet(k,v){try{localStorage.setItem(k,v);}catch(e){}}
/* 3.3 «Первые 5»: кладёт построенную таблицу t в box; строки после пятой прячутся, кнопка «Показать все (N)». total и cap нужны, если список обрезан лимитом (тогда подпись «N, лимит L»). Состояние: list_<id>. */
function fold5(box,id,t,total,cap){
  var rows=t.querySelectorAll('tbody tr'),n=rows.length,all=(total===undefined||total===null)?n:total;
  box.appendChild(t);
  if(n<=5)return;
  var open=lsGet('list_'+id)==='1',b=el('button','showall');b.type='button';
  function paint(){for(var i=5;i<n;i++)rows[i].style.display=open?'':'none';
    b.textContent=open?'Свернуть до 5 строк':'Показать все ('+((cap&&all>cap)?(all+', лимит '+cap):all)+')';}
  b.addEventListener('click',function(){open=!open;lsSet('list_'+id,open?'1':'0');paint();});
  paint();box.appendChild(b);
}
/* 3.3 Сворачиваемый блок: все строки остаются, сворачивается весь блок стрелкой. Состояние: fold_<id> ('0' = свёрнут). */
function foldHead(h,title,n,open){h.textContent=(open?'▾ ':'▸ ')+title+((n===undefined||n===null)?'':' ('+n+')');h.setAttribute('aria-expanded',open?'true':'false');}
function foldWrap(id,title,n,content){
  var w=el('div','foldw'),h=el('button','foldh'),b=el('div','foldb'),open=lsGet('fold_'+id)!=='0';
  h.type='button';b.appendChild(content);w.appendChild(h);w.appendChild(b);
  function paint(){b.style.display=open?'':'none';foldHead(h,title,n,open);}
  h.addEventListener('click',function(){open=!open;lsSet('fold_'+id,open?'1':'0');paint();});
  paint();return w;
}
function foldStatic(node,id,title){
  var h=el('button','foldh'),open=lsGet('fold_'+id)!=='0';h.type='button';
  function paint(){node.style.display=open?'':'none';foldHead(h,title,null,open);}
  h.addEventListener('click',function(){open=!open;lsSet('fold_'+id,open?'1':'0');paint();});
  node.parentNode.insertBefore(h,node);paint();
}
function svg(tag,at,text){var e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(var k in at)e.setAttribute(k,at[k]);if(text!==undefined)e.textContent=text;return e;}

