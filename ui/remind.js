/* ---------- Напоминания ---------- */
var RM={rows:[],busy:false};
function rmIdle(){RM.busy=false;$('rm-scan').disabled=false;$('rm-all').disabled=!RM.rows.some(function(r){return r.g.ok&&!r.done;});}
function rmSendOne(r,text){
  r.b.disabled=true;
  return ap('/api/remind/send',{buyer:r.g.buyer,text:text}).then(function(x){
    r.st.textContent=x.note||'Отправлено.';r.done=!x.error_site;if(x.error_site)r.b.disabled=false;return x;});
}
function remScan(){
  say('Ищу заказы и проверяю чаты покупателей (один запрос на покупателя, может занять около минуты)…');
  $('rm-all').disabled=true;
  return ap('/api/remind/preview').then(function(d){say('');var c=d.counts;
    var okn=d.groups.filter(function(g){return g.ok;});
    $('rm-sum').textContent='На странице заказов: '+c.on_page+'; оплачены и ждут подтверждения: '+c.paid+'; моложе суток: '+c.young+'; без даты: '+c.no_date+'; без покупателя: '+c.no_buyer+'; у поддержки (пропущено): '+c.support+'. Покупателей для напоминания: '+okn.length+'.';
    var box=$('rm-tbl');box.textContent='';RM.rows=[];
    if(!d.groups.length){box.appendChild(el('div','empty','Подходящих заказов нет.'));rmIdle();return;}
    var t=el('table'),th=el('thead'),hr=el('tr');['','Покупатель','Заказы','Статус'].forEach(function(h){hr.appendChild(el('th','',h));});th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
    d.groups.forEach(function(g){var tr=el('tr'),td=el('td','btns'),st=el('td','',g.ok?('можно напомнить'+(g.note?' ('+g.note+')':'')):g.reason);
      var b=el('button','b','Напомнить');b.type='button';b.disabled=!g.ok;
      var r={g:g,b:b,st:st,done:false};RM.rows.push(r);
      b.addEventListener('click',function(){
        if(RM.busy)return;
        var text=$('rm-text').value.trim();if(!text){say('Введите текст напоминания.',true);return;}
        if(!confirm('Отправить напоминание покупателю «'+g.name+'» по заказам: '+g.orders.map(function(o){return '#'+o.id;}).join(', ')+'?'))return;
        rmSendOne(r,text).then(function(){say('');rmIdle();}).catch(function(e){say(e.message,true);b.disabled=false;});});
      td.appendChild(b);tr.appendChild(td);tr.appendChild(el('td','',g.name));
      var otd=el('td','');otd.style.whiteSpace='pre-line';g.orders.forEach(function(o,k){if(k)otd.appendChild(document.createTextNode('\n'));otd.appendChild(ordLink(o.id));otd.appendChild(document.createTextNode(' ('+o.age+' ч'+(o.sent?', напоминаний '+o.sent:'')+') '+o.title));});tr.appendChild(otd);tr.appendChild(st);tb.appendChild(tr);});
    t.appendChild(tb);box.appendChild(t);rmIdle();
  }).catch(function(e){say(e.message,true);rmIdle();});
}
function remAll(){
  if(RM.busy)return;
  var text=$('rm-text').value.trim();if(!text){say('Введите текст напоминания.',true);return;}
  var todo=RM.rows.filter(function(r){return r.g.ok&&!r.done;});
  if(!todo.length){say('Некому напоминать: сначала нажмите «Найти заказы».');return;}
  var n=0;todo.forEach(function(r){n+=r.g.orders.length;});
  if(!confirm('Отправить напоминание '+todo.length+' покупателям (заказов: '+n+')?\n\nТекст:\n'+text.slice(0,300)+'\n\nСообщения уходят по одному, с паузами, примерно '+Math.max(1,Math.ceil(todo.length*5/60))+' мин. При первой ошибке остановлюсь.'))return;
  RM.busy=true;$('rm-all').disabled=true;$('rm-scan').disabled=true;
  var i=0,sent=0;
  (function next(){
    if(i>=todo.length){rmIdle();say('Готово: отправлено '+sent+' из '+todo.length+'. Ответ сайта в таблице, проверьте чаты.');return;}
    var r=todo[i++];say('Отправляю '+i+' из '+todo.length+': '+r.g.name+'…');
    rmSendOne(r,text).then(function(x){
      if(x.error_site){rmIdle();say('Остановился: сайт вернул ошибку ('+x.error_site+'). Отправлено '+sent+' из '+todo.length+'.',true);return;}
      sent++;next();
    }).catch(function(e){r.b.disabled=false;rmIdle();say('Остановился на «'+r.g.name+'»: '+e.message+' Отправлено '+sent+' из '+todo.length+'.',true);});
  })();
}
$('rm-scan').addEventListener('click',remScan);
$('rm-all').addEventListener('click',remAll);

