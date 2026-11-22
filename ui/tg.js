/* ---------- Telegram ---------- */
var TGW={};
function tgLoad(){
  return api('/api/tg/status').then(function(d){
    var c=d.cfg,box=$('tg-events');
    $('tg-enabled').checked=c.enabled;$('tg-commands').checked=c.commands;$('tg-min').value=c.min_amount;$('tg-tz').value=c.tz;$('tg-time').value=c.summary_time;
    box.textContent='';TGW={};
    d.events.forEach(function(e){var lb=el('label'),i=el('input');i.type='checkbox';i.checked=!!c.events[e.key];TGW[e.key]=i;lb.appendChild(i);lb.appendChild(el('span','',' '+e.label));box.appendChild(lb);});
    var t='Токен: '+d.token+'; chat_id: '+d.chat+'. Отправлено: '+d.sent+(d.failed?', не доставлено: '+d.failed:'')+(d.queued?', в очереди: '+d.queued:'')+'.';
    if(d.err)t+=' Последняя ошибка'+(d.err_at?' ('+d.err_at.replace('T',' ')+')':'')+': '+d.err+'.';
    if(c.commands&&d.poll)t+=' Команды: '+d.poll+'.';
    if(d.chat!=='нет'&&d.chat!=='неверный формат'&&!d.private)t+=' chat_id похож на группу или канал: оповещения идут, команды отключены.';
    if(d.foreign)t+=' Сообщений от чужих чатов проигнорировано: '+d.foreign+'.';
    t+=' Время по вашему поясу сейчас: '+d.now_local+'. Заказов запомнено: '+d.orders_seen+(d.summary_day?'; последняя сводка за '+d.summary_day:'')+'.';
    var s=$('tg-state');s.textContent=t;s.style.color=(d.err||d.token!=='есть'||d.chat==='нет'||d.chat==='неверный формат')?'var(--x)':'';
  }).catch(function(e){say(e.message,true);});
}
$('tg-save').addEventListener('click',function(){
  var ev={};Object.keys(TGW).forEach(function(k){ev[k]=TGW[k].checked;});
  ap('/api/tg/settings',{enabled:$('tg-enabled').checked,commands:$('tg-commands').checked,events:ev,min_amount:Number($('tg-min').value||0),tz:Number($('tg-tz').value),summary_time:$('tg-time').value}).then(function(){say('Настройки Telegram сохранены.');return tgLoad();}).catch(function(e){say(e.message,true);});
});
$('tg-test').addEventListener('click',function(){
  $('tg-test').disabled=true;
  ap('/api/tg/test').then(function(){say('Тестовое сообщение отправлено, проверьте Telegram.');}).catch(function(e){say(e.message,true);}).then(function(){$('tg-test').disabled=false;return tgLoad();});
});
function autoLogin(){
  return api('/api/acc/status').then(function(s){
    AC.logged=s.logged;
    if(s.logged||!s.keyfile||s.locked)return;
    say('Вхожу в аккаунт по golden_key.txt…');
    return ap('/api/acc/login',{key:'',use_file:true,remember:false}).then(function(){AC.logged=true;say('');}).catch(function(e){say('Автовход не удался: '+e.message,true);});
  }).catch(function(){});
}
api('/api/autopilot/status').then(apBanner).catch(function(){});
load('').then(autoLogin).then(function(){var h=(location.hash||'').replace('#','');var ok=TABS.some(function(t){return t[0]===h;});show(ok?h:'home');});
})();
