/* ---------- нужен вход (Сообщения, Напоминания, Статистика) ---------- */
function needLogin(prefix,then){
  return api('/api/acc/status').then(function(s){
    $(prefix+'-login').style.display=s.logged?'none':'block';$(prefix+'-main').style.display=s.logged?'block':'none';
    if(s.logged)then();
  }).catch(function(e){say(e.message,true);});
}

