/* ---------- Статистика ---------- */
function stReport(){
  return ap('/api/stat/report',{days:Number($('st-days').value)}).then(function(d){
    say('');$('st-fee').value=d.fee;
    $('st-info').textContent='Заказов в кэше: '+d.orders_total+(d.updated?', обновлено '+d.updated:', ещё не загружались (нажмите «Загрузить заказы»)')+(d.nodate?', без даты: '+d.nodate:'')+'. Только рубли.';
    var c=$('st-cards');c.textContent='';
    [['Выполнено',d.tot.closed],['Оплачено, ждут',d.tot.paid],['Возвраты',d.tot.refund],['Выручка, ₽',money(d.tot.rev)],['Ожидается, ₽',money(d.tot.pending)],['Возвраты, ₽',money(d.tot.refund_sum)]].forEach(function(x){
      var s=el('div','sc');s.appendChild(el('div','sl',x[0]));s.appendChild(el('div','sv',String(x[1])));c.appendChild(s);});
    var mx=1;d.daily.forEach(function(x){if(x.rev>mx)mx=x.rev;});
    var W=700,HH=150,bw=W/d.daily.length,s=svg('svg',{viewBox:'0 0 '+W+' '+(HH+22),width:'100%'});
    d.daily.forEach(function(x,i){var h=Math.round((HH-10)*x.rev/mx),r=svg('rect',{x:i*bw+4,y:HH-h,width:bw-8,height:h,style:'fill:var(--acc)'});r.appendChild(svg('title',{},x.date+': '+x.n+' зак., '+money(x.rev)+' ₽'));s.appendChild(r);
      s.appendChild(svg('text',{x:i*bw+bw/2,y:HH+14,'text-anchor':'middle','font-size':10,style:'fill:var(--mut)'},x.date));});
    var dv=$('st-daily');dv.textContent='';dv.appendChild(el('h3','','Выручка по дням (14 дней)'));dv.appendChild(s);
    var box=$('st-lots');box.textContent='';
    if(!d.lots.length){box.appendChild(el('div','empty','За период заказов нет.'));return;}
    var t=el('table'),th=el('thead'),hr=el('tr');['Лот','Вып.','Оплач.','Возвр.','Выручка','Ожид.','За 7 дн.','Себестоимость, ₽','Прибыль, ₽','Метки'].forEach(function(h,i){hr.appendChild(el('th',(i>0&&i<9)?'num':'',h));});th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
    d.lots.forEach(function(r){var tr=el('tr');var tt=el('td','',r.title);tt.appendChild(el('span','tag',r.lot_id?('ID '+r.lot_id):'без ID: детали заказов не загружены, считается по названию'));tr.appendChild(tt);[r.closed,r.paid,r.refund,money(r.rev),money(r.pending),r.n7].forEach(function(v){tr.appendChild(el('td','num',String(v)));});
      var cs=el('td','num'),i=el('input');i.type='number';i.min='0';i.style.width='90px';i.value=(r.cost===null||r.cost===undefined)?'':r.cost;
      i.addEventListener('change',function(){ap('/api/stat/cost',{title:r.title,cost:i.value}).then(function(){say('');return stReport();}).catch(function(e){say(e.message,true);});});
      cs.appendChild(i);tr.appendChild(cs);tr.appendChild(el('td','num',money(r.profit)));tr.appendChild(el('td','',r.tags));tb.appendChild(tr);});
    t.appendChild(tb);box.appendChild(foldWrap('st-lots','Лоты за период',d.lots.length,t));
  }).catch(function(e){say(e.message,true);});
}
$('st-days').addEventListener('change',stReport);
$('st-sync').addEventListener('click',function(){
  var pg=Number($('st-pages').value)||3;
  if(!confirm('Загрузить страницы заказов (запросов до '+pg+', с паузами)? Читаются только заказы и суммы, переписка не открывается.'))return;
  $('st-sync').disabled=true;say('Загружаю заказы…');
  ap('/api/stat/sync',{pages:pg}).then(function(d){$('st-sync').disabled=false;say('Страниц: '+d.pages+', получено заказов: '+d.got+', новых: '+d.new+', всего в кэше: '+d.total+(d.more?'. Есть ещё страницы, запустите снова с большим числом.':'.'));return stReport();})
   .catch(function(e){$('st-sync').disabled=false;say(e.message,true);});
});
$('st-feesave').addEventListener('click',function(){ap('/api/stat/fee',{fee:$('st-fee').value}).then(function(){say('');return stReport();}).catch(function(e){say(e.message,true);});});
$('st-bal').addEventListener('click',function(){ap('/api/stat/profile').then(function(d){$('st-balv').textContent=d.balance?('Баланс: '+d.balance):d.note;}).catch(function(e){say(e.message,true);});});
$('st-pos').addEventListener('click',function(){
  ap('/api/stat/position').then(function(d){var box=$('st-pos-t');box.textContent='';
    if(!d.rows.length){box.appendChild(el('div','empty',d.note||'Нет данных.'));return;}
    fold5(box,'st-pos-t',tbl(['Лот','Цена','Место по цене','Медиана рынка','Заказов за 7 дн.','за 30 дн.','Подсказка'],d.rows.map(function(r){return[r.title,money(r.price)+' ₽',r.rank+' из '+r.of,money(r.median)+' ₽',String(r.n7),String(r.n30),r.suggest?('поднять до '+money(r.suggest)+' ₽'):'—'];}),[1,2,3,4,5]));
    box.appendChild(el('div','cnt','Данные витрины на '+(d.date||'—')+'. Подсказка — оценка: цена не выше медианы и не больше +25%.'));
  }).catch(function(e){say(e.message,true);});
});

