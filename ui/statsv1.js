/* ---------- Статистика v1 ---------- */
function pct(v){return(v===null||v===undefined)?'—':(Math.round(v*1000)/10)+' %';}
function sv1Pend(){return ap('/api/stat/v1/rewards').then(function(d){
  var box=$('sv-pend');box.textContent='';$('rw-u').value=$('rw-u').value||d.settings.reward_units;
  if(!d.pending.length)box.appendChild(el('div','cnt','Нет заказов с 5★ без записанной награды (нужны детали заказов и дата акции у лота).'));
  else{var t=el('table'),th=el('thead'),hr=el('tr');['','Заказ','Лот','Название','Дата'].forEach(function(h){hr.appendChild(el('th','',h));});th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
    d.pending.forEach(function(p){var tr=el('tr'),td=el('td','btns'),b=el('button','b','Выдано');b.type='button';
      b.addEventListener('click',function(){if(!confirm('Записать награду за заказ #'+p.order+' ('+d.settings.reward_units+' ед.) как выданную?'))return;b.disabled=true;
        ap('/api/stat/v1/reward_add',{order:p.order,stars:5,units:d.settings.reward_units}).then(function(){say('');sv1All();}).catch(function(e){say(e.message,true);b.disabled=false;});});
      td.appendChild(b);tr.appendChild(td);tr.appendChild(el('td','id','#'+p.order));tr.appendChild(el('td','id',p.lot));tr.appendChild(el('td','',p.title));tr.appendChild(el('td','',p.date));tb.appendChild(tr);});
    t.appendChild(tb);box.appendChild(foldWrap('sv-pend','Заказы с 5★ без награды',d.pending.length,t));}
  var rw=$('sv-rw');rw.textContent='';rw.appendChild(el('div','cnt','Журнал (последние 100), всего потрачено на награды: '+money(d.total)+' ₽ (факт)'));
  if(d.items.length)fold5(rw,'sv-rw',tbl(['Дата','Заказ','Лот','Звёзды','Единиц','Стоимость, ₽','Источник'],d.items.map(function(r){return[r.date,'#'+r.order,r.lot||'—',String(r.stars||'—'),String(r.units),money(r.cost),r.src||''];}),[3,4,5]));
}).catch(function(e){say(e.message,true);});}
function sv1Exp(){return ap('/api/stat/v1/expenses').then(function(d){
  var c=$('ex-c');if(!c.options.length)d.cats.forEach(function(x){var o=el('option','',x);o.value=x;c.appendChild(o);});
  if(!$('ex-d').value)$('ex-d').value=d.today;
  var box=$('sv-ex');box.textContent='';if(d.items.length)fold5(box,'sv-ex',tbl(['Дата','Категория','Сумма, ₽','Комментарий'],d.items.map(function(e){return[e.date,e.category,money(e.amount),e.comment||''];}),[2]));
}).catch(function(e){say(e.message,true);});}
function sv1Set(){return ap('/api/stat/v1/settings_get').then(function(d){
  var box=$('sv-set');box.textContent='';
  d.order.forEach(function(k){var lb=el('label'),i=el('input');i.type='text';i.style.width='80px';i.value=d.settings[k];i.setAttribute('data-k',k);lb.appendChild(el('span','',d.labels[k]+': '));lb.appendChild(i);lb.style.display='block';box.appendChild(lb);});
}).catch(function(e){say(e.message,true);});}
function sv1Report(){
  return ap('/api/stat/v1/report',{days:Number($('sv-days').value)}).then(function(d){
    say('');var w=$('sv-warn');w.textContent='';d.warnings.forEach(function(x){w.appendChild(el('div','msg bad',x));w.lastChild.style.display='block';});
    var t=d.tot,box=$('sv-tot');box.textContent='';
    box.appendChild(tbl(['Итог по магазину','₽','Тип'],[
      ['Выручка (только «Закрыт»), заказов '+t.closed,money(t.rev),'факт'],['Возвраты отдельно, '+t.refund_n+' шт.',money(t.refund_sum),'факт'],
      ['Комиссия FunPay ('+d.fee+' %)',money(t.comm),'оценка'],['Себестоимость',money(t.cost),'оценка'],
      ['РАСХОДЫ НА НАГРАДЫ ЗА ОТЗЫВЫ',money(t.rw),'факт'],['Прочие расходы',money(t.other),'факт'],
      ['ЧИСТАЯ ПРИБЫЛЬ после всех расходов',money(t.net),'оценка']],[1]));
    var tp=$('sv-tips');tp.textContent='';
    if(!d.tips.length)tp.appendChild(el('div','cnt','Подсказок нет: условия порогов не выполнены или данных мало.'));
    d.tips.forEach(function(x){var b=el('div','box');b.appendChild(el('b','',x.action.toUpperCase()+' · '+x.title+' [ID '+x.lot+'] '));b.appendChild(el('span','lab o','оценка'));b.appendChild(el('div','cnt',x.basis));tp.appendChild(b);});
    var lb=$('sv-lotstbl');lb.textContent='';
    if(!d.lots.length){lb.appendChild(el('div','empty','За период заказов нет.'));return;}
    var tb=el('table'),th=el('thead'),hr=el('tr');
    ['Лот','Закр. (ф)','Выручка (ф)','Возвр. шт (ф)','Доля возвр. (о)','Комиссия (о)','Себест. за ед. (ввод)','Себест. (о)','Награды (ф)','Прибыль (о)','На заказ (о)','Отзывов (ф)','Конв. в отзыв (о)','Доля 5★ (о)','Стоимость отзыва (о)','Акция с','Акция: вердикт (о)'].forEach(function(h,i){hr.appendChild(el('th',i>0&&i<15?'num':'',h));});
    th.appendChild(hr);tb.appendChild(th);var bd=el('tbody');
    d.lots.forEach(function(x){var tr=el('tr');tr.appendChild(el('td','',x.title+(x.id?' [ID '+x.id+']':'')));
      [x.closed,money(x.rev),x.refund,pct(x.refund_share),money(x.comm)].forEach(function(v){tr.appendChild(el('td','num',String(v)));});
      var cs=el('td','num');if(x.id){var i=el('input');i.type='text';i.style.width='70px';i.value=(x.unit_cost===null||x.unit_cost===undefined)?'':x.unit_cost;
        i.addEventListener('change',function(){ap('/api/stat/v1/cost',{lot:x.id,cost:i.value}).then(function(){say('');sv1Report();}).catch(function(e){say(e.message,true);});});cs.appendChild(i);}
      tr.appendChild(cs);
      [money(x.cost),money(x.rw_cost),money(x.profit),money(x.profit_order),x.reviews,pct(x.conv),pct(x.five_share),money(x.cost_review)].forEach(function(v){tr.appendChild(el('td','num',String(v)));});
      var ps=el('td','');if(x.id){var di=el('input');di.type='text';di.placeholder='ГГГГ-ММ-ДД';di.style.width='100px';di.value=(x.promo&&x.promo.since)||'';
        di.addEventListener('change',function(){ap('/api/stat/v1/promo',{lot:x.id,since:di.value.trim()}).then(function(){say('');sv1Report();sv1Pend();}).catch(function(e){say(e.message,true);});});ps.appendChild(di);}
      tr.appendChild(ps);var pv=x.promo||{},vt='';
      if(pv.verdict){vt=pv.verdict+(pv.R!==undefined?': Р='+money(pv.R)+' ₽ (Д='+pv.D+' ед. × П='+money(pv.P)+' − З='+money(pv.Z)+'); безубыточность '+pv.T+' ед. на отзыв':'')+(pv.why?' ('+pv.why+')':'')+'; ед. до/после '+pv.E_before+'/'+pv.E_after;}
      tr.appendChild(el('td','',vt));bd.appendChild(tr);});
    tb.appendChild(bd);lb.appendChild(foldWrap('sv-lotstbl','Лоты за период',d.lots.length,tb));
  }).catch(function(e){say(e.message,true);});
}
function sv1All(){sv1Report();sv1Pend();sv1Exp();sv1Set();}
$('sv-rep').addEventListener('click',sv1Report);$('sv-days').addEventListener('change',sv1Report);
$('sv-det').addEventListener('click',function(){var n=Number($('sv-lim').value)||20;
  if(!confirm('Открыть страницы заказов (до '+n+' запросов, с паузами)? Читаются только ID лота и звёзды отзыва.'))return;
  $('sv-det').disabled=true;say('Загружаю детали заказов…');
  ap('/api/stat/v1/details',{limit:n}).then(function(d){$('sv-det').disabled=false;var m='Обработано заказов: '+d.done+', с ID лота: '+d.linked+', со звёздами: '+d.with_stars+', осталось: '+d.left+(d.left?'. Нажмите ещё раз.':'.')+(d.diag?' '+d.diag:'');sv1Pend();sv1Exp();sv1Set();sv1Report().then(function(){say(m);});})
   .catch(function(e){$('sv-det').disabled=false;say(e.message,true);});});
function svLots(){
  ap('/api/stat/v1/lots').then(function(d){
    var box=$('sv-lotbox');box.textContent='';box.style.display='block';
    box.appendChild(el('div','cnt','Все лоты из ваших заказов. Если лот переименовали, программа видит его как новый: у нового лота выберите старый и нажмите «Объединить», заказы сложатся вместе. Объединение можно отменить кнопкой «Разъединить». Себестоимость у объединённых берётся от оставляемого лота.'));
    var roots=d.lots.filter(function(l){return !l.into;});
    var t=el('table'),hr=el('tr');['Название','ID','Заказов','Последний','Тип','Объединить с'].forEach(function(c){hr.appendChild(el('th','',c));});
    var th=el('thead');th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
    d.lots.forEach(function(l){
      var tr=el('tr');tr.appendChild(el('td','',l.title));tr.appendChild(el('td','',l.id));tr.appendChild(el('td','num',String(l.orders)));tr.appendChild(el('td','',l.last));
      tr.appendChild(el('td','',l.syn?'условный номер (нет в профиле)':'настоящий'));
      var td=el('td','');
      if(l.into){var to=d.lots.filter(function(x){return x.id===l.into;})[0];td.appendChild(el('span','','объединён с: '+(to?to.title.slice(0,50):l.into)+' '));
        var b=el('button','b','Разъединить');b.type='button';b.addEventListener('click',function(){ap('/api/stat/v1/lot_unmerge',{from:l.id}).then(function(){svLots();sv1Report();}).catch(function(e){say(e.message,true);});});td.appendChild(b);}
      else{var sel=el('select');sel.appendChild(el('option','','— выберите лот —'));sel.firstChild.value='';
        roots.forEach(function(x){if(x.id===l.id)return;var o=el('option','',x.title.slice(0,60)+' ('+x.orders+')');o.value=x.id;sel.appendChild(o);});
        var b2=el('button','b','Объединить');b2.type='button';b2.addEventListener('click',function(){
          if(!sel.value){say('Сначала выберите, с каким лотом объединить.',true);return;}
          var tt=roots.filter(function(x){return x.id===sel.value;})[0];
          if(!confirm('Считать «'+l.title.slice(0,60)+'» тем же лотом, что «'+(tt?tt.title.slice(0,60):sel.value)+'»? Заказы сложатся вместе в отчёте.'))return;
          ap('/api/stat/v1/lot_merge',{from:l.id,to:sel.value}).then(function(){say('');svLots();sv1Report();}).catch(function(e){say(e.message,true);});});
        td.appendChild(sel);td.appendChild(b2);}
      tr.appendChild(td);tb.appendChild(tr);});
    t.appendChild(tb);var wrap=el('div');wrap.style.overflowX='auto';wrap.appendChild(t);box.appendChild(foldWrap('sv-lotbox','Лоты из заказов',d.lots.length,wrap));
    if(!d.lots.length)box.appendChild(el('div','empty','Лотов с ID пока нет: нажмите «Загрузить детали заказов».'));
  }).catch(function(e){say(e.message,true);});}
$('sv-lots').addEventListener('click',function(){show('merge');});
$('sv-exp').addEventListener('click',function(){ap('/api/stat/v1/export',{days:Number($('sv-days').value)}).then(function(d){var o=$('sv-exp-out');o.textContent='Сохранено: '+d.csv+'\nи '+d.txt+'\n\n'+d.text;o.style.display='block';say('');}).catch(function(e){say(e.message,true);});});
$('rw-add').addEventListener('click',function(){ap('/api/stat/v1/reward_add',{order:$('rw-o').value,stars:Number($('rw-s').value),units:Number($('rw-u').value)}).then(function(){say('');$('rw-o').value='';sv1All();}).catch(function(e){say(e.message,true);});});
$('ex-add').addEventListener('click',function(){ap('/api/stat/v1/expense_add',{date:$('ex-d').value,category:$('ex-c').value,amount:$('ex-a').value,comment:$('ex-m').value}).then(function(){say('');$('ex-a').value='';$('ex-m').value='';sv1All();}).catch(function(e){say(e.message,true);});});
$('sv-setsave').addEventListener('click',function(){var v={};Array.prototype.forEach.call($('sv-set').querySelectorAll('input'),function(i){v[i.getAttribute('data-k')]=i.value;});
  ap('/api/stat/v1/settings_set',{values:v}).then(function(){say('Настройки сохранены.');sv1All();}).catch(function(e){say(e.message,true);});});

