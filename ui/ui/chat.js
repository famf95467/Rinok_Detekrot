/* ---------- Сообщения ---------- */
var CH={node:null,rows:[]};
function chatList(){
  say('Загружаю диалоги…');
  return ap('/api/chat/list').then(function(d){CH.rows=d.rows;say('');var box=$('ch-list');box.textContent='';
    d.rows.forEach(function(r){var it=el('div','ci'+(r.unread?' un':'')+(r.id===CH.node?' cur':''));it.appendChild(el('div','',r.name+(r.time?' · '+r.time:'')));it.appendChild(el('div','cnt',r.last));
      it.addEventListener('click',function(){chatOpen(r);});box.appendChild(it);});
  }).catch(function(e){say(e.message,true);});
}
function chatOpen(r){
  CH.node=r.id;$('ch-title').textContent=r.name;$('ch-note').textContent='';$('ch-text').disabled=false;$('ch-send').disabled=false;
  Array.prototype.forEach.call($('ch-list').children,function(c){c.className=c.className.replace(' cur','');});
  chatHist();chatList();
}
function chatHist(){
  say('Загружаю сообщения…');
  return ap('/api/chat/history',{node:CH.node}).then(function(d){say('');var h=$('ch-hist');h.textContent='';
    d.messages.forEach(function(m){var b=el('div','mm'+(m.mine?' me':''));b.appendChild(el('small','',m.author+(m.time?' · '+m.time:'')));b.appendChild(document.createTextNode(m.text));h.appendChild(b);});
    h.scrollTop=h.scrollHeight;}).catch(function(e){say(e.message,true);});
}
$('ch-reload').addEventListener('click',chatList);
$('ch-send').addEventListener('click',function(){
  var t=$('ch-text').value.trim();if(!CH.node||!t)return;
  if(!confirm('Отправить это сообщение собеседнику?'))return;
  $('ch-send').disabled=true;
  ap('/api/chat/send',{node:CH.node,text:t}).then(function(d){$('ch-text').value='';$('ch-note').textContent=d.note||'';$('ch-send').disabled=false;chatHist();})
   .catch(function(e){say(e.message,true);$('ch-send').disabled=false;});
});

