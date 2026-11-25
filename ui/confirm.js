/* ---------- Подтверждения ---------- */
var CF={orders:[],sel:{}};
function cfTime(q){var t=prompt(q+'\nФормат: ГГГГ-ММ-ДД ЧЧ:ММ. Пусто = сейчас. «Отмена» = не делать.','');return t===null?null:t.trim();}
function cfCall(url,body){return ap(url,body).then(function(r){say('');return cfLoad().then(function(){return r;});}).catch(function(e){say(e.message,true);cfLoad();});}
function cfLoad(){
  return api('/api/confirm/list'+($('cf-all').checked?'?all=1':'')).then(function(d){CF.orders=d.orders;
    var ct=$('cf-tpl');if(ct&&!ct.value.trim())ct.value=(d.templates&&d.templates.length)?d.templates[0]:'Здравствуйте! Заказ {order} оплачен больше суток назад. Если всё работает, пожалуйста, подтвердите выполнение заказа на сайте. Спасибо!';
    Object.keys(CF.sel).forEach(function(k){if(!d.orders.some(function(o){return o.id===k;}))delete CF.sel[k];});
    $('cf-sum').textContent='Заказов в списке: '+d.orders.length+'. Просрочен таймер '+d.hours+' ч: '+d.overdue+'. Готово к тикету: '+d.ready+'.';
    cfRender();cfLog(d.log);}).catch(function(e){say(e.message,true);});
}
function cfBtn(txt,fn,title){var b=el('button','b',txt);b.type='button';if(title)b.title=title;b.addEventListener('click',fn);return b;}
var CF_V=['problem','wait','ready','remind'];
function cfCat(o){return CF_V.indexOf(o.verdict)>=0?o.verdict:'other';}
function cfRender(){
  var box=$('cf-tbl');box.textContent='';
  var f=$('cf-flt').value,cn={problem:0,wait:0,ready:0,remind:0,other:0};CF.orders.forEach(function(o){cn[cfCat(o)]++;});
  var opts=$('cf-flt').options,nm={all:'Все',problem:'Проблемный',wait:'Ждёт 24 ч',ready:'Можно писать тикет',remind:'Напомнить',other:'Прочие'};
  for(var oi=0;oi<opts.length;oi++){var ov=opts[oi].value;opts[oi].text=nm[ov]+' ('+(ov==='all'?CF.orders.length:cn[ov])+')';}
  var all=CF.orders,rows=f==='all'?all:all.filter(function(o){return cfCat(o)===f;});
  if(!rows.length){box.appendChild(el('div','empty',!all.length?'Заказов в учёте нет. Добавьте вручную или нажмите «Синхронизировать с сайтом».':(f==='all'?'Заказов в учёте нет.':'В этой категории заказов нет.')));return;}
  var t=el('table'),th=el('thead'),hr=el('tr');
  ['','Заказ','Лот','Сумма','Учёт','Таймер','Статус','Чат проверен','Тикет','Заметка','Действия'].forEach(function(h){hr.appendChild(el('th','',h));});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  rows.forEach(function(o){
    var tr=el('tr'),done=(o.status==='confirmed'||o.status==='refunded');
    var c0=el('td'),cb=el('input');cb.type='checkbox';cb.checked=!!CF.sel[o.id];cb.disabled=done;
    cb.addEventListener('change',function(){if(cb.checked)CF.sel[o.id]=true;else delete CF.sel[o.id];});c0.appendChild(cb);tr.appendChild(c0);
    var ol=el('td','id');ol.appendChild(ordLink(o.id));tr.appendChild(ol);tr.appendChild(el('td','',o.lot||'—'));tr.appendChild(el('td','num',o.price?String(o.price):'—'));
    var st=o.status_ru+(o.status==='confirmed'&&o.confirmed_by?' ('+o.confirmed_by+')':'');tr.appendChild(el('td','',st));
    tr.appendChild(el('td',o.overdue?'warn':'',o.left||'—'));
    var ctd=el('td');
    if(o.verdict==='done'){ctd.appendChild(el('div','cnt','—'));}
    else{
      var vb=el('div','sv',o.verdict_ru);vb.style.fontSize='14px';vb.style.color={problem:'var(--x)',unclear:'var(--x)',ready:'var(--s)',admin_done:'var(--s)',buyer_done:'var(--s)',wait:'var(--n)',remind:'var(--acc)'}[o.verdict]||'';ctd.appendChild(vb);
      ctd.appendChild(el('div','cnt',(o.verdict_short||'')+(o.verdict_src?' · '+o.verdict_src:'')));
      var cc=o.chat_check;
      if(cc&&cc.detail){var more=el('a','ol','детали');more.href='javascript:void(0)';var dv=el('div','cnt',cc.detail+' (проверка '+cc.at.replace('T',' ').slice(0,16)+')');dv.style.display='none';dv.style.maxWidth='360px';
        more.addEventListener('click',function(){dv.style.display=dv.style.display==='none'?'block':'none';});ctd.appendChild(more);ctd.appendChild(dv);}
    }
    tr.appendChild(ctd);
    var c6=el('td'),ck=el('input');ck.type='checkbox';ck.checked=o.chat_ok;ck.disabled=done;
    ck.title='Ручное переопределение: вы сами проверили чат. Снимает статус «Проблемный» и «Автор не определён», таймер 24 ч не отменяет.';
    ck.addEventListener('change',function(){
      if(ck.checked){
        if(!confirm('Подтверждаете: вы сами проверили чат заказа #'+o.id+', услуга оказана, покупатель однозначно просто забыл подтвердить?')){ck.checked=false;return;}
        var u=prompt('Ссылка на диалог (необязательно, начинается с https://funpay.com/):','');if(u===null){ck.checked=false;return;}
        cfCall('/api/confirm/chat-ok',{id:o.id,url:u.trim()});
      }else cfCall('/api/confirm/chat-ok',{id:o.id,off:true});});
    c6.appendChild(ck);tr.appendChild(c6);
    var tk=o.ticket_sent_at?'отправлен '+o.ticket_sent_at.replace('T',' '):(o.ticket_at?'текст готов':(o.ticket_blockers.length&&!done?'нельзя: '+o.ticket_blockers.join('; '):(done?'—':'можно')));
    tr.appendChild(el('td','cnt',tk));
    var nt=el('td'),ni=el('input');ni.type='text';ni.maxLength=300;ni.value=o.note||'';ni.style.width='150px';
    ni.addEventListener('change',function(){ap('/api/confirm/note',{id:o.id,note:ni.value}).then(function(){say('');}).catch(function(e){say(e.message,true);});});
    nt.appendChild(ni);tr.appendChild(nt);
    var ac=el('td','btns');
    if(!done){
      if(o.status==='paid')ac.appendChild(cfBtn('Выдан',function(){var t=cfTime('Время выдачи заказа #'+o.id);if(t===null)return;cfCall('/api/confirm/deliver',{id:o.id,at:t});}));
      if(o.verdict==='remind')ac.appendChild(cfBtn('Напомнить',function(){show('remind');},'Открывает вкладку «Напоминания». Сообщение отсюда не отправляется.'));
      ac.appendChild(cfBtn(o.status==='reminded'?'Напомнил ещё раз':'Напомнил',function(){var t=cfTime('Время напоминания покупателю по заказу #'+o.id+' (запускает таймер '+24+' ч)');if(t===null)return;cfCall('/api/confirm/remind',{id:o.id,at:t});}));
      ac.appendChild(cfBtn('Подтвердил',function(){var t=cfTime('Время, когда покупатель подтвердил заказ #'+o.id);if(t===null)return;cfCall('/api/confirm/confirm',{id:o.id,at:t}).then(function(r){if(r&&r.warn)say(r.warn);});}));
    }
    tr.appendChild(ac);tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(t);
}
function cfLog(rows){
  var box=$('cf-log');box.textContent='';
  if(!rows||!rows.length){box.appendChild(el('div','cnt','Записей нет.'));return;}
  var t=tbl(['Время','Заказ','Действие','Подробности','Результат'],rows.slice(0,100).map(function(r){return[r.time.replace('T',' '),'',r.action,r.detail,r.ok?'ок':'отказ'];}));
  Array.prototype.forEach.call(t.querySelectorAll('tbody tr'),function(tr,i){var r=rows[i];if(r&&r.order)tr.children[1].appendChild(ordLink(r.order));});
  box.appendChild(t);
}
$('cf-all').addEventListener('change',cfLoad);
$('cf-flt').addEventListener('change',cfRender);
$('cf-chk').addEventListener('click',function(){
  var tpl=($('cf-tpl').value||'').trim();
  if(!tpl){say('Впишите текст напоминания в поле над таблицей.',true);return;}
  if(!confirm('Проверить чаты всех покупателей: один запрос на каждого, с паузами, партиями по 30 подряд до конца списка. Читаются последние сообщения (до 60), переписка не сохраняется, ничего не отправляется. Сравнивать с текстом из поля над таблицей. Продолжить?'))return;
  $('cf-chk').disabled=true;
  var tot={buyers:0,ok:0,bad:0,reasons:{},moved:{}},pass=0;
  function add(dst,src){Object.keys(src||{}).forEach(function(k){dst[k]=(dst[k]||0)+src[k];});}
  function done(msg,bad){$('cf-chk').disabled=false;$('cf-flt').value='all';say(msg,bad);return cfLoad();}
  function summary(left){
    var rs=Object.keys(tot.reasons).map(function(k){return k+': '+tot.reasons[k];}).join(', ');
    var mv=Object.keys(tot.moved).map(function(k){return k+': '+tot.moved[k];}).join(', ');
    return 'Проверено покупателей: '+tot.buyers+'. Подходят: '+tot.ok+', не подходят: '+tot.bad+(rs?' ('+rs+')':'')+'.'+(mv?' Сменили статус из-за системных сообщений FunPay: '+mv+'.':'')+(left?' Не проверено: '+left+' покупателей, нажмите ещё раз.':'');
  }
  (function next(){
    pass++;say('Проверяю чаты, партия '+pass+(tot.buyers?' (уже проверено '+tot.buyers+')':'')+', это может занять несколько минут…');
    ap('/api/confirm/chat-check',{template:tpl}).then(function(d){
      tot.buyers+=d.buyers;tot.ok+=d.ok;tot.bad+=d.bad;add(tot.reasons,d.reasons);add(tot.moved,d.moved);
      if(d.left>0&&d.buyers>0){return cfLoad().then(next);}
      return done(summary(d.left));
    }).catch(function(e){
      $('cf-chk').disabled=false;say((tot.buyers?'Остановилось после '+tot.buyers+' проверенных покупателей. ':'')+e.message,true);cfLoad();});
  })();});
$('cf-reload').addEventListener('click',cfLoad);
$('cf-add').addEventListener('click',function(){
  ap('/api/confirm/add',{id:$('cf-nid').value,lot:$('cf-nlot').value,price:$('cf-nprice').value,buyer:$('cf-nbuyer').value,at:$('cf-nat').value}).then(function(){
    ['cf-nid','cf-nlot','cf-nprice','cf-nbuyer','cf-nat'].forEach(function(i){$(i).value='';});say('');return cfLoad();}).catch(function(e){say(e.message,true);});});
$('cf-sync').addEventListener('click',function(){
  if(!confirm('Загрузить страницу заказов /orders/trade (один запрос) и обновить статусы «Закрыт» и «Возврат»? Переписка не открывается.'))return;
  $('cf-sync').disabled=true;say('Загружаю заказы…');
  ap('/api/confirm/sync').then(function(d){$('cf-sync').disabled=false;say('Синхронизация: новых '+d.new+', закрыто '+d.confirmed+', возвратов '+d.refunded+'.');return cfLoad();})
   .catch(function(e){$('cf-sync').disabled=false;say(e.message,true);});});
$('cf-ticket').addEventListener('click',function(){
  var ids=Object.keys(CF.sel);
  ap('/api/confirm/ticket',{ids:ids,again:$('cf-again').checked}).then(function(r){
    var n=$('cf-resnote'),p=$('cf-text');$('cf-res').style.display='block';
    var parts=[];
    if(r.ready.length)parts.push('Текст тикета подготовлен для заказов: '+r.ready.map(function(i){return '#'+i;}).join(', ')+'. Файл: '+r.file+'. НИЧЕГО НЕ ОТПРАВЛЕНО: скопируйте текст и отправьте тикет сами, затем нажмите «Отметить тикет отправлен».');
    else parts.push('Нет заказов, для которых можно подготовить тикет.');
    if(r.skipped.length)parts.push('Пропущены: '+r.skipped.map(function(s){return '#'+s.id+' ('+s.why.join('; ')+')';}).join(' | '));
    n.textContent=parts.join(' ');p.textContent=r.text||'';say('');return cfLoad();}).catch(function(e){say(e.message,true);});});
$('cf-sent').addEventListener('click',function(){
  var ids=Object.keys(CF.sel);if(!ids.length){say('Отметьте галочками заказы, по которым вы отправили тикет.',true);return;}
  if(!confirm('Подтверждаете: тикет по заказам '+ids.map(function(i){return '#'+i;}).join(', ')+' вы отправили в поддержку сами?'))return;
  ap('/api/confirm/ticket-sent',{ids:ids}).then(function(){CF.sel={};say('');return cfLoad();}).catch(function(e){say(e.message,true);});});

