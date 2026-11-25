/* ---------- Продажи конкурентов по остатку ---------- */
var MSD=false;
function msFill(st,force){var c=st.cfg;if(force||!MSD){$('ms-on').checked=c.enabled;$('ms-int').value=c.interval_min;$('ms-node').value=c.node;$('ms-max').value=c.max_sale;catRefresh('ms-node');}
  var s=$('ms-state'),t;
  if(st.state==='stopped'){s.className='state bad';t='Остановлено: '+(st.stopped||'защита сайта')+'. Опрос не идёт до завтра, повтор запрещён.';}
  else if(st.state==='off'){s.className='state';t='Опрос выключен.'+(st.note?' '+st.note+'.':'');}
  else if(st.state==='error'){s.className='state bad';t='Сбой: '+st.err+' ('+(st.err_at||'').replace('T',' ')+'). Следующая попытка через интервал.';}
  else{s.className='state ok';t='Работает'+(st.last?', последний проход '+st.last.replace('T',' '):', первый проход скоро')+'.'+(st.note?' '+st.note+'.':'');}
  s.textContent=t;
  var l=st.last_stats||{},i='Лотов на странице: '+st.lots+', с числом в остатке: '+st.with_amount+'. Проходов сегодня: '+st.day.passes+(st.day.errors?', сбоев: '+st.day.errors:'')+(st.day.incomplete?', неполных страниц: '+st.day.incomplete:'')+' (в сутки возможно '+Math.round(1440/st.cfg.interval_min)+').';
  if(st.passes_run)i+=' Последний проход: продажи '+l.sale+', пополнения '+l.restock+', смена количества '+l.bulk+', без изменений '+l.same+', новые '+l.new+', пропущено из-за паузы '+l.stale+', без числа '+l.noamount+'.';
  $('ms-info').textContent=i;}
function msReport(){
  return api('/api/ms/report?days='+encodeURIComponent($('ms-days').value)+'&q='+encodeURIComponent($('ms-q').value.trim())).then(function(d){
    var c=$('ms-cards');c.textContent='';
    [['Продано, шт. (оценка)',d.tot.sold],['Выручка, ₽ (оценка)',money(d.tot.rev)],['Событий',d.tot.events],['Продавцов',d.tot.sellers],['Лотов',d.tot.lots]].forEach(function(x){var b=el('div','sc');b.appendChild(el('div','sl',x[0]));b.appendChild(el('div','sv',String(x[1])));c.appendChild(b);});
    var a=$('ms-sellers');a.textContent='';
    if(!d.sellers.length)a.appendChild(el('div','empty','Продаж за период не засчитано.'));
    else fold5(a,'ms-sellers',tbl(['Продавец','Продано, шт.','Выручка, ₽','Событий','Лотов','Последняя'],d.sellers.map(function(r){return[r.seller,String(r.sold),money(r.rev),String(r.events),String(r.lots),r.last];}),[1,2,3,4]));
    var b=$('ms-lots');b.textContent='';
    if(!d.lots.length)b.appendChild(el('div','empty','Нет данных.'));
    else fold5(b,'ms-lots',tbl(['Лот','Продавец','Цена','Продано, шт.','Выручка, ₽','Событий'],d.lots.map(function(r){return[r.title,r.seller,r.price===null?'—':money(r.price)+' ₽',String(r.sold),money(r.rev),String(r.events)];}),[2,3,4,5]));
    var p=$('ms-daily');p.textContent='';
    fold5(p,'ms-daily',tbl(['День','Продано, шт.','Выручка, ₽','Проходов','Сбоев','Неполных страниц'],d.per_day.map(function(r){return[r.date,String(r.sold),money(r.rev),String(r.passes),String(r.errors),String(r.incomplete)];}),[1,2,3,4,5]));
  }).catch(function(e){say(e.message,true);});}
function msLoad(force){
  return api('/api/ms/status').then(function(st){msFill(st,force);return msReport();}).catch(function(e){say(e.message,true);});}
['ms-on','ms-int','ms-node','ms-max'].forEach(function(id){$(id).addEventListener('input',function(){MSD=true;});});
$('ms-save').addEventListener('click',function(){
  var on=$('ms-on').checked,m=Number($('ms-int').value);
  if(on&&!confirm('Включить опрос страницы категории раз в '+m+' мин? Это '+Math.round(1440/Math.max(1,m))+' запросов в сутки как гость. При любом признаке защиты сайта опрос остановится до завтра.'))return;
  ap('/api/ms/settings',{enabled:on,interval_min:m,node:Number($('ms-node').value),max_sale:Number($('ms-max').value)}).then(function(){MSD=false;say('');return msLoad(true);}).catch(function(e){say(e.message,true);});});
$('ms-reload').addEventListener('click',function(){msLoad(false);});$('ms-days').addEventListener('change',msReport);$('ms-q').addEventListener('input',msReport);
setInterval(function(){if(view==='sales')msLoad(false);},30000);
catHint('ms-node');
