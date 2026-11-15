/* ---------- Автопилот ---------- */
function apFill(st,force){
  var c=st.cfg;
  if(force||!AP_DIRTY){$('ap-enabled').checked=c.enabled;$('ap-every').value=c.every_min;$('ap-max').value=c.max_sends;$('ap-age').value=c.max_age_days;
    $('ap-remind').checked=c.remind;$('ap-review').checked=c.review_request;$('ap-reward').checked=c.reward;$('ap-ticket').checked=c.ticket_prepare;$('ap-raise').checked=!!c.raise;$('ap-refund').checked=c.refund;$('ap-rbelow').value=c.refund_below;$('ap-rmax').value=c.refund_max_price;$('ap-text').value=c.remind_text;}
  var s=$('ap-state'),r=st.ready||{},any=c.remind||c.review_request||c.reward||c.refund;
  s.className='state '+((st.paused||st.locked||!st.logged)?'bad':'ok');
  s.textContent=(st.locked?'Сессия заблокирована сайтом. ':(!st.logged?'Нет входа в аккаунт. ':''))+(st.paused?'Отправки на паузе. ':'')
    +(c.enabled?'Автопилот работает':'Автопилот выключен')+(st.running?' (идёт цикл)':'')+(st.ended?'; последний цикл: '+st.ended.replace('T',' '):'')+(st.next&&c.enabled?'; следующий: '+st.next.replace('T',' '):'')
    +'. Готово к отправке: напоминаний '+(r.remind||0)+', просьб об отзыве '+(r.review_request||0)+', наград '+(r.reward||0)+', возвратов '+(r.refund||0)+(any?'.':' (отправки выключены).');
  $('ap-resume').style.display=st.paused?'inline-block':'none';
  var box=$('ap-steps');box.textContent='';
  if(!st.steps.length)box.appendChild(el('div','cnt','Цикл ещё не выполнялся: первый запуск через ~45 секунд после старта программы.'));
  else box.appendChild(tbl(['Шаг','Результат'],st.steps.map(function(x){return [x.name+(x.ok?'':' (!)'),x.text];})));
  var lg=$('ap-log');lg.textContent='';
  if(st.log.length)lg.appendChild(tbl(['Время','Шаг','Результат'],st.log.map(function(x){return [x.time.replace('T',' '),x.step,(x.ok?'':'(!) ')+x.text];})));
}
var AP_DIRTY=false;
['ap-enabled','ap-every','ap-max','ap-age','ap-remind','ap-review','ap-reward','ap-ticket','ap-text','ap-refund','ap-rbelow','ap-rmax'].forEach(function(id){$(id).addEventListener('input',function(){AP_DIRTY=true;});});
function apLoad(force){return api('/api/autopilot/status').then(function(st){apFill(st,force);apBanner(st);}).catch(function(e){say(e.message,true);});}
function apBanner(st){
  var b=$('ap-banner'),a=st.attention||[];
  if(!a.length){b.style.display='none';document.title='FunPay Detector';return;}
  b.textContent=a.map(function(x){return x.text;}).join(' · ');b.style.display='block';document.title='(!) FunPay Detector';
}
$('ap-banner').addEventListener('click',function(){show('auto');});
$('ap-save').addEventListener('click',function(){
  var nolim=Number($('ap-max').value)===0;
  var on=[['ap-remind','напоминания покупателям'],['ap-review','просьбы об отзыве'],['ap-reward','награды'],['ap-refund','ВОЗВРАТ ДЕНЕГ при оценке ниже '+$('ap-rbelow').value+(Number($('ap-rmax').value)>0?' (сумма до '+$('ap-rmax').value+' ₽)':' (сумма без ограничения)')]].filter(function(p){return $(p[0]).checked;});
  if(on.length&&!confirm('Включить автоотправку: '+on.map(function(p){return p[1];}).join(', ')+'?\nСообщения будут уходить покупателям сами, без подтверждения, пока программа открыта.'+(nolim?'\nЛимит сообщений за цикл снят: уйдут ВСЕ готовые (по возвратам остаётся не больше 3 за цикл).':'')))return;
  ap('/api/autopilot/settings',{enabled:$('ap-enabled').checked,every_min:Number($('ap-every').value),max_sends:Number($('ap-max').value),max_age_days:Number($('ap-age').value),
    remind:$('ap-remind').checked,review_request:$('ap-review').checked,reward:$('ap-reward').checked,refund:$('ap-refund').checked,refund_below:Number($('ap-rbelow').value),refund_max_price:Number($('ap-rmax').value),ticket_prepare:$('ap-ticket').checked,raise:$('ap-raise').checked,remind_text:$('ap-text').value})
   .then(function(){AP_DIRTY=false;say('Настройки сохранены.');return apLoad(true);}).catch(function(e){say(e.message,true);});
});
$('ap-run').addEventListener('click',function(){ap('/api/autopilot/run').then(function(){say('Цикл запущен, результат появится через минуту.');setTimeout(function(){apLoad(false);},5000);}).catch(function(e){say(e.message,true);});});
$('ap-resume').addEventListener('click',function(){ap('/api/autopilot/resume').then(function(){return apLoad(false);}).catch(function(e){say(e.message,true);});});
setInterval(function(){if(view==='auto')apLoad(false);else api('/api/autopilot/status').then(apBanner).catch(function(){});},30000);
