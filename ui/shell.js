<script>
(function(){
'use strict';
var TABS=[['home','Главная'],['marks','Отметки'],['prices','Цены'],['data','Данные'],['hist','История'],['acc','Аккаунт'],['chat','Сообщения'],['remind','Напоминания'],['confirm','Подтверждения'],['review','Отзывы'],['auto','Автопилот'],['stats','Статистика'],['sales','Продажи'],['merge','Слияние лотов']];
var MARKS=['скрипт','ниша','нет'],CLS={'скрипт':'s','ниша':'n','нет':'x'};
var lots=[],filter='none',data={},view='home',pdata=null,pollT=null;
function $(id){return document.getElementById(id);}
function say(t,bad){var b=$('msg');b.textContent=t||'';b.className='msg'+(bad?' bad':'');b.style.display=t?'block':'none';}
function api(url,opts){return fetch(url,opts).then(function(r){return r.json().catch(function(){return {};}).then(function(j){if(!r.ok)throw new Error(j.error||('Ошибка '+r.status));return j;});},function(){throw new Error('Программа не отвечает. Проверьте, что чёрное окно не закрыто.');});}
document.addEventListener('click',function(e){if(!e.target||e.target.id!=='im-go')return;var f=$('im-file').files[0],r=$('im-res');if(!f){r.textContent='Выберите zip-файл.';return;}if(!confirm('Загрузить '+f.name+' и заменить совпадающие файлы данных?'))return;r.textContent='Загрузка…';fetch('/api/import_zip',{method:'POST',headers:{'Content-Type':'application/zip'},body:f}).then(function(x){return x.json();}).then(function(j){r.textContent=j.error?('Ошибка: '+j.error):('Готово: файлов '+j.files+', пропущено '+j.skipped+(j.skipped_sample&&j.skipped_sample.length?' ('+j.skipped_sample.join(', ')+')':'')+'. Теперь перезапустите сервис в Railway.');}).catch(function(x){r.textContent='Ошибка: '+x.message;});});
function ap(u,b){return api(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function numOrNull(v){var x=parseFloat(String(v).replace(',','.'));return isNaN(x)?null:x;}
function money(v){return(v===null||v===undefined||v==='')?'—':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:2});}
function qinc(a,i){var m=a.length-1,j=Math.floor(i*m/4),d=i*m-j*4;return j+1<a.length?(a[j]*(4-d)+a[j+1]*d)/4:a[j];}
function stats(v){if(!v.length)return null;var a=v.slice().sort(function(x,y){return x-y;}),n=a.length,m=n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2;return{n:n,min:a[0],max:a[n-1],med:m,q1:n>=5?qinc(a,1):null,q3:n>=5?qinc(a,3):null};}
function ordLink(id){var a=el('a','ol','#'+id);a.href='https://funpay.com/orders/'+encodeURIComponent(id)+'/';a.target='_blank';a.rel='noopener noreferrer';a.title='Открыть страницу заказа на FunPay';return a;}
function tbl(cols,rows,nc){var t=el('table'),th=el('thead'),hr=el('tr');cols.forEach(function(c,i){hr.appendChild(el('th',nc&&nc.indexOf(i)>=0?'num':'',c));});th.appendChild(hr);t.appendChild(th);var tb=el('tbody');rows.forEach(function(r){var tr=el('tr');r.forEach(function(v,i){tr.appendChild(el('td',nc&&nc.indexOf(i)>=0?'num':'',v));});tb.appendChild(tr);});t.appendChild(tb);return t;}
function svg(tag,at,text){var e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(var k in at)e.setAttribute(k,at[k]);if(text!==undefined)e.textContent=text;return e;}

