/* ---------- Автопилот ---------- */
var AP_LAST={};
function apFill(st,force){
  var c=st.cfg;AP_LAST=c;
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
  else fold5(box,'ap-steps',tbl(['Шаг','Результат'],st.steps.map(function(x){return [x.name+(x.ok?'':' (!)'),x.text];})));
  var lg=$('ap-log');lg.textContent='';
  if(st.log.length)fold5(lg,'ap-log',tbl(['Время','Шаг','Результат'],st.log.map(function(x){return [x.time.replace('T',' '),x.step,(x.ok?'':'(!) ')+x.text];})));
}
var AP_DIRTY=false;
function apLoad(force){return api('/api/autopilot/status').then(function(st){apFill(st,force);apBanner(st);}).catch(function(e){say(e.message,true);});}
function apBanner(st){
  var b=$('ap-banner'),a=st.attention||[];
  if(!a.length){b.style.display='none';document.title='FunPay Detector';return;}
  b.textContent=a.map(function(x){return x.text;}).join(' · ');b.style.display='block';document.title='(!) FunPay Detector';
}
$('ap-banner').addEventListener('click',function(){show('auto');});
/* Автосохранение: изменение поля сохраняется само через ~1 с. Опасные включения (автоотправка, автовозврат, снятие лимита) спрашивают подтверждение в момент включения. */
var AP_VER=0,AP_T=null,AP_SAVING=false,AP_AGAIN=false;
var AP_SEND=[['ap-remind','напоминания покупателям'],['ap-review','просьбы об отзыве'],['ap-reward','награды'],['ap-refund','ВОЗВРАТ ДЕНЕГ']];
var AP_NUM=[['ap-every','Цикл, минут'],['ap-max','Не больше сообщений за цикл'],['ap-age','Брать заказы не старше, дней'],['ap-rbelow','Оценка ниже'],['ap-rmax','Сумма заказа не больше']];
function apValid(){
  for(var i=0;i<AP_NUM.length;i++){var n=$(AP_NUM[i][0]),v=n.value.trim(),x=Number(v);
    if(v===''||!isFinite(x)||x!==Math.floor(x)||(n.min!==''&&x<Number(n.min))||(n.max!==''&&x>Number(n.max)))
      return '«'+AP_NUM[i][1]+'»: нужно целое число'+(n.min!==''?' от '+n.min:'')+(n.max!==''?' до '+n.max:'')+'.';}
  return '';
}
function apAnySend(){return AP_SEND.some(function(p){return $(p[0]).checked;});}
function apLimOff(){var v=$('ap-max').value.trim();return v!==''&&Number(v)===0;}   // пустое поле не равно нулю
function apUndirty(){AP_DIRTY=AP_SAVING||AP_T!==null;}   // после отказа поля снова обновляются с сервера, если нет других несохранённых правок
function apGuard(id){
  var n=$(id),lim=apLimOff();
  if(AP_SEND.some(function(p){return p[0]===id;})&&n.checked){
    var name=AP_SEND.filter(function(p){return p[0]===id;})[0][1];
    if(id==='ap-refund')name+=' при оценке ниже '+$('ap-rbelow').value+(Number($('ap-rmax').value)>0?' (сумма до '+$('ap-rmax').value+' ₽)':' (сумма без ограничения)')+'. Деньги уходят покупателю, отменить нельзя';
    if(!confirm('Включить автоотправку: '+name+'?\nСообщения будут уходить покупателям сами, без подтверждения, пока программа открыта.'+(lim?'\nЛимит сообщений за цикл снят: уйдут ВСЕ готовые (по возвратам остаётся не больше 3 за цикл).':''))){n.checked=false;apUndirty();return false;}
  }
  if((id==='ap-rbelow'||id==='ap-rmax')&&$('ap-refund').checked){
    if(!confirm('Изменить условия автовозврата? Сейчас: оценка ниже '+$('ap-rbelow').value+', сумма '+(Number($('ap-rmax').value)>0?'до '+$('ap-rmax').value+' ₽':'без ограничения')+'. Деньги уходят покупателю, отменить нельзя.')){
      $('ap-rbelow').value=AP_LAST.refund_below;$('ap-rmax').value=AP_LAST.refund_max_price;apUndirty();return false;}
  }
  if(id==='ap-max'&&lim&&apAnySend()){
    if(!confirm('Снять лимит сообщений за цикл? Уйдут ВСЕ готовые сообщения (по возвратам остаётся не больше 3 за цикл).')){$('ap-max').value=AP_LAST.max_sends;apUndirty();return false;}
  }
  return true;
}
function apSchedule(delay){AP_VER++;AP_DIRTY=true;clearTimeout(AP_T);AP_T=setTimeout(apAuto,delay);}
function apAuto(){
  AP_T=null;
  if(AP_SAVING){AP_AGAIN=true;return;}
  var bad=apValid(),tag=$('ap-saved');
  if(bad){tag.textContent='Не сохранено: '+bad;tag.className='cnt warn';return;}
  AP_SAVING=true;var v=AP_VER;tag.textContent='Сохраняю…';tag.className='cnt';
  ap('/api/autopilot/settings',{enabled:$('ap-enabled').checked,every_min:Number($('ap-every').value),max_sends:Number($('ap-max').value),max_age_days:Number($('ap-age').value),
    remind:$('ap-remind').checked,review_request:$('ap-review').checked,reward:$('ap-reward').checked,refund:$('ap-refund').checked,refund_below:Number($('ap-rbelow').value),refund_max_price:Number($('ap-rmax').value),ticket_prepare:$('ap-ticket').checked,raise:$('ap-raise').checked,remind_text:$('ap-text').value})
   .then(function(){AP_SAVING=false;if(AP_VER===v)AP_DIRTY=false;tag.textContent='Сохранено '+new Date().toLocaleTimeString('ru-RU');tag.className='cnt';say('');
     if(AP_AGAIN){AP_AGAIN=false;apAuto();return;}return apLoad(false);})
   .catch(function(e){AP_SAVING=false;AP_AGAIN=false;tag.textContent='Не сохранено: '+e.message;tag.className='cnt warn';say('Настройки автопилота не сохранены: '+e.message,true);});
}
['ap-enabled','ap-remind','ap-review','ap-reward','ap-ticket','ap-raise','ap-refund'].forEach(function(id){
  $(id).addEventListener('change',function(){if(!apGuard(id))return;apSchedule(300);});});
['ap-every','ap-max','ap-age','ap-rbelow','ap-rmax'].forEach(function(id){
  $(id).addEventListener('input',function(){AP_DIRTY=true;});
  $(id).addEventListener('change',function(){if(!apGuard(id))return;apSchedule(600);});});
$('ap-text').addEventListener('input',function(){apSchedule(1500);});
$('ap-run').addEventListener('click',function(){ap('/api/autopilot/run').then(function(){say('Цикл запущен, результат появится через минуту.');setTimeout(function(){apLoad(false);},5000);}).catch(function(e){say(e.message,true);});});
$('ap-resume').addEventListener('click',function(){ap('/api/autopilot/resume').then(function(){return apLoad(false);}).catch(function(e){say(e.message,true);});});
setInterval(function(){if(view==='auto')apLoad(false);else api('/api/autopilot/status').then(apBanner).catch(function(){});},30000);
