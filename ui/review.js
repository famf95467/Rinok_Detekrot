/* ---------- Отзывы ---------- */
var RV={cfg:null,orders:[],lots:[],rules:[],rev:0};
function rvLoad(){
  return api('/api/review/list').then(function(d){
    RV.cfg=d.settings;RV.orders=d.orders;RV.lots=d.lots_seen||[];
    $('rv-sum').textContent='Подтверждённых заказов: '+d.total+'. Готовы к просьбе: '+d.ready+'. Просьба отправлена: '+d.sent+'. Готовы к выдаче награды: '+d.reward_ready+'.'+rvCostText(d.costs)+(d.total>d.orders.length?' Показаны первые '+d.orders.length+'.':'');
    if(!RVS.dirty){
      $('rv-def').value=d.settings.default;$('rv-delay').value=d.settings.delay_hours;RV.rev=d.settings.rev||0;
      RV.rules=d.settings.lots.map(function(r){return JSON.parse(JSON.stringify(r));});
      rvRules();
    }else rvStamp('Есть несохранённые правки: данные с сервера не подставлены, чтобы не затереть их.',true);
    rvRender();rvLog(d.log);
    if(!AC.rows.length&&!RV.triedMy){RV.triedMy=true;rvEnsureMyLots();}
  }).catch(function(e){say(e.message,true);});
}
function rvCostText(c){
  if(!c||(!c.given_n&&!c.ready_n))return '';
  var m=function(v){return Number(v).toLocaleString('ru-RU',{maximumFractionDigits:2});};
  var t=' Расходы на награды: выдано '+c.given_n+' ('+c.given_units+' шт.) на '+m(c.spent)+' ₽'+(c.est_n?' (у '+c.est_n+' выдач, сделанных до ввода цены, по текущей цене)':'')+
    '. Готово к выдаче: '+c.ready_units+' шт. ≈ '+m(c.ready_cost)+' ₽.';
  if(!c.any_cost)t+=' Цена штуки не указана ни в одном правиле: впишите «Стоимость 1 шт.» в правило, тогда расходы посчитаются.';
  return t;
}
function rvMyTitles(){
  var seen={},out=[];
  (typeof AC!=='undefined'?AC.rows:[]).forEach(function(r){
    var t=String(r.title||'').replace(/\s+/g,' ').trim(),k=t.toLowerCase();
    if(t&&!seen[k]){seen[k]=1;out.push(t);}});
  return out.sort(function(a,b){return a.localeCompare(b,'ru');});
}
function rvEnsureMyLots(){
  if(AC.rows.length)return Promise.resolve();
  return ap('/api/acc/offers').then(function(d){AC.rows=d.rows;rvRules();}).catch(function(e){RV.myErr=e.message;rvRules();});
}
var RV_THANKS='Спасибо за отзыв на {stars} из 5! Ваша награда по заказу {order}:\n{reward}';
function rvNewRule(){return{key:'',matches:[],text:$('rv-def').value,reward:{enabled:false,stars:5,units:1,unit_cost:0,type:'stock',endless_text:'',thanks:RV_THANKS}};}
function rvIn(type,val,w){var i=el('input');i.type=type;i.value=val;if(w)i.style.width=w;return i;}
/* автосохранение: правка -> через 0,7 с запись в папку проекта; при закрытии вкладки дописываем сразу */
var RVS={t:null,dirty:false,seq:0,chain:Promise.resolve()};
function rvPayload(){return {rev:RV.rev,default:$('rv-def').value,delay_hours:$('rv-delay').value,lots:RV.rules.filter(function(r){return r.matches.length;})};}
function rvStamp(t,bad){var s=$('rv-savest');s.textContent=t;s.style.color=bad?'var(--x)':'';}
function rvAuto(){RVS.dirty=true;RVS.seq++;rvStamp('Изменения…');clearTimeout(RVS.t);RVS.t=setTimeout(function(){rvSave(true);},700);}
function rvSave(silent){
  clearTimeout(RVS.t);
  var run=function(){
    var sent=RVS.seq;
    return ap('/api/review/settings',rvPayload()).then(function(r){
      if(r&&r.rev!==undefined)RV.rev=r.rev;
      if(RVS.seq===sent)RVS.dirty=false;
      rvStamp('Сохранено '+new Date().toLocaleTimeString('ru-RU'));
      if(!silent)say('Шаблоны сохранены.');return true;
    }).catch(function(e){rvStamp('НЕ сохранено: '+e.message,true);say('Правила НЕ сохранены: '+e.message,true);return false;});
  };
  RVS.chain=RVS.chain.then(run,run);   /* сохранения идут по очереди, чтобы номер версии не расходился */
  return RVS.chain;
}
window.addEventListener('pagehide',function(){
  if(!RVS.dirty)return;
  try{fetch('/api/review/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(rvPayload()),keepalive:true});}catch(e){}
});
function rvFrag(t){return t.slice(0,40).trim();}
function rvOwner(frag,self){
  for(var k=0;k<RV.rules.length;k++){if(RV.rules[k]===self)continue;
    for(var m=0;m<RV.rules[k].matches.length;m++)if(RV.rules[k].matches[m].toLowerCase()===frag.toLowerCase())return k+1;}
  return 0;
}
function rvRules(){
  var box=$('rv-rules');box.textContent='';
  if(!RV.rules.length){box.appendChild(el('div','cnt','Правил нет: всем лотам отправляется общий шаблон. Нажмите «Добавить правило».'));return;}
  RV.rules.forEach(function(r,i){
    var w=el('div','box');
    var hd=el('div','bar');hd.appendChild(el('b','','Правило '+(i+1)));
    var x=el('button','b','Удалить правило');x.type='button';
    x.addEventListener('click',function(){if(!confirm('Удалить правило '+(i+1)+'? Список промокодов у него останется в файле, но выдавать из него будет нельзя.'))return;RV.rules.splice(i,1);rvRules();rvAuto();});
    hd.appendChild(x);w.appendChild(hd);
    /* лоты правила */
    w.appendChild(el('div','fh','Лоты этого правила ('+r.matches.length+')'));
    var chips=el('div','bar');chips.style.gap='6px';
    if(!r.matches.length)chips.appendChild(el('span','warn','Выберите хотя бы один лот ниже, иначе правило не сохранится.'));
    r.matches.forEach(function(m,mi){
      var c=el('span','tag',m+' ✕');c.style.cssText='cursor:pointer;border:1px solid var(--line);border-radius:10px;padding:2px 8px;margin:0';c.title='Убрать лот из правила';
      c.addEventListener('click',function(){r.matches.splice(mi,1);rvRules();rvAuto();});chips.appendChild(c);});
    w.appendChild(chips);
    var det=el('details');var sm=el('summary','','Выбрать лоты из моих (на аккаунте)');det.appendChild(sm);
    var q=el('input');q.type='text';q.placeholder='Поиск по названию';q.style.cssText='max-width:300px;margin:6px 0';det.appendChild(q);
    var list=el('div','slist');list.style.maxHeight='220px';det.appendChild(list);
    function fill(){
      list.textContent='';var ql=q.value.trim().toLowerCase(),n=0,titles=rvMyTitles();
      if(!titles.length)list.appendChild(el('div','note',RV.myErr?('Лоты аккаунта не загружены: '+RV.myErr):'Ваши лоты ещё не загружены: подождите или войдите на вкладке «Аккаунт».'));
      titles.forEach(function(t){
        if(ql&&t.toLowerCase().indexOf(ql)<0)return;
        var f=rvFrag(t),own=rvOwner(f,r),lb=el('label'),c=el('input');c.type='checkbox';
        c.checked=r.matches.some(function(m){return m.toLowerCase()===f.toLowerCase();});c.disabled=!!own&&!c.checked;
        c.addEventListener('change',function(){
          if(c.checked){if(!r.matches.some(function(m){return m.toLowerCase()===f.toLowerCase();}))r.matches.push(f);}
          else r.matches=r.matches.filter(function(m){return m.toLowerCase()!==f.toLowerCase();});
          rvRules();rvAuto();});
        lb.appendChild(c);lb.appendChild(el('span','',' '+t.slice(0,90)+(own?' (уже в правиле '+own+')':'')));list.appendChild(lb);n++;});
      if(titles.length&&!n)list.appendChild(el('div','note','Ничего не найдено.'));
    }
    q.addEventListener('input',fill);fill();
    if(r.open||!r.matches.length){det.open=true;}
    det.addEventListener('toggle',function(){r.open=det.open;});
    w.appendChild(det);
    /* текст */
    w.appendChild(el('div','fh','Текст просьбы (подстановки: {order} {lot} {price} {link} {promise})'));
    var t=el('textarea','full');t.rows=3;t.maxLength=1000;t.value=r.text;t.addEventListener('input',function(){r.text=t.value;rvAuto();});w.appendChild(t);
    /* награда */
    var R=r.reward,rb=el('div','bar'),lb=el('label'),cb=rvIn('checkbox','');cb.checked=R.enabled;
    lb.appendChild(cb);lb.appendChild(el('span','',' Награда за отзыв с оценкой '));
    var st=rvIn('number',R.stars,'60px');st.min=1;st.max=5;
    var ty=el('select');[['stock','Штучный (список промокодов)'],['endless','Бесконечный (ссылка или текст)']].forEach(function(p){var o=el('option','',p[1]);o.value=p[0];if(R.type===p[0])o.selected=true;ty.appendChild(o);});
    var un=rvIn('number',R.units,'80px');un.min=1;un.max=1000;var unl=el('label');unl.appendChild(el('span','',' Штук за отзыв: '));unl.appendChild(un);
    var uc=rvIn('number',R.unit_cost||0,'90px');uc.min=0;uc.step='0.01';var ucl=el('label');ucl.appendChild(el('span','',' Стоимость 1 шт., ₽: '));ucl.appendChild(uc);ucl.title='Сколько вам обходится одна штука. Нужна только для подсчёта расходов на награды.';
    rb.appendChild(lb);rb.appendChild(st);rb.appendChild(el('span','cnt',' из 5. Тип: '));rb.appendChild(ty);rb.appendChild(unl);rb.appendChild(ucl);w.appendChild(rb);
    var en=el('div');en.appendChild(el('div','fh','Бесконечная награда: текст или ссылка (одинаковые для всех)'));
    var et=el('textarea','full');et.rows=2;et.maxLength=1000;et.value=R.endless_text;et.addEventListener('input',function(){R.endless_text=et.value;rvAuto();});en.appendChild(et);w.appendChild(en);
    var left=r.key&&RV.cfg.stock[r.key]!==undefined?RV.cfg.stock[r.key]:null;
    var sk=el('div');sk.appendChild(el('div','fh','Список промокодов на все лоты правила (одна строка = одна штука). Осталось: '+(left===null?'правило ещё не сохранено':left)));
    var sa=el('textarea','full');sa.rows=4;sa.placeholder='PROMO-1\nPROMO-2';sk.appendChild(sa);
    var sb=el('div','bar');
    [['Заменить список',false],['Добавить к списку',true]].forEach(function(p){var b=el('button','b',p[0]);b.type='button';b.addEventListener('click',function(){
      if(!r.matches.length){say('Сначала выберите лоты правила.',true);return;}
      if(!sa.value.trim()&&!p[1]&&!confirm('Список пустой: текущий список наград этого правила будет очищен. Продолжить?'))return;
      rvSave(true).then(function(ok){if(!ok)throw new Error('Правило не сохранено, смотрите сообщение справа от задержки.');
        return rvKeys();}).then(function(){var rr=RV.rules[i];
        return ap('/api/review/stock',{key:rr.key||rr.matches[0],text:sa.value,append:p[1]});})
        .then(function(d){say('Список правила: теперь '+d.count+' шт.');return rvLoad();}).catch(function(e){say(e.message,true);});});sb.appendChild(b);});
    sk.appendChild(sb);w.appendChild(sk);
    w.appendChild(el('div','fh','Сообщение с наградой (подстановки: {order} {stars} {reward}; {reward} обязателен)'));
    var th=el('textarea','full');th.rows=2;th.maxLength=1000;th.value=R.thanks;th.addEventListener('input',function(){R.thanks=th.value;rvAuto();});w.appendChild(th);
    function dis(){[st,ty,un,uc,et,th].forEach(function(e){e.disabled=!cb.checked;});
      en.style.display=R.type==='endless'?'block':'none';sk.style.display=R.type==='stock'?'block':'none';unl.style.display=R.type==='stock'?'inline':'none';ucl.style.display=R.type==='stock'?'inline':'none';}
    cb.addEventListener('change',function(){R.enabled=cb.checked;dis();rvAuto();});
    st.addEventListener('input',function(){R.stars=Number(st.value);rvAuto();});un.addEventListener('input',function(){R.units=Number(un.value);rvAuto();});uc.addEventListener('input',function(){R.unit_cost=uc.value;rvAuto();});
    ty.addEventListener('change',function(){R.type=ty.value;dis();rvAuto();});
    dis();box.appendChild(w);});
}
/* после сохранения у новых правил появляется key: подтягиваем его с сервера, не теряя несохранённые черновики */
function rvKeys(){
  return api('/api/review/list').then(function(d){
    RV.cfg=d.settings;
    RV.rules.forEach(function(r){
      var s=d.settings.lots.find(function(x){return x.matches.length&&x.matches.some(function(m){return r.matches.indexOf(m)>=0;});});
      if(s)r.key=s.key;});});
}
function rvSend(o){
  return ap('/api/review/send',{id:o.id}).then(function(r){
    if(!r.sent)throw new Error('Сайт вернул ошибку: '+r.error_site+'. Просьба не отмечена отправленной.');
    return rvLoad().then(function(){return r;});});
}
function rvScan(){
  if(!confirm('Найти подтверждённые заказы по коду страниц заказов? Запросы страниц заказов идут по одному с паузой, партиями до конца списка. Ничего не отправляется покупателям. Если заказ у нас помечен подтверждённым, а на странице он не «Закрыт», пометка будет снята.'))return;
  $('rv-scan').disabled=true;
  var t={checked:0,confirmed:0,corrected:0,reverted:0,refunded:0,unclear:0,stars:0},pass=0,prev=null;
  function fin(){$('rv-scan').disabled=false;}
  (function next(){
    pass++;say('Ищу подтверждённые заказы по страницам, партия '+pass+(t.checked?' (проверено '+t.checked+')':'')+'… это может занять несколько минут.');
    ap('/api/review/scan').then(function(r){
      Object.keys(t).forEach(function(k){t[k]+=(r[k]||0);});
      var stuck=(r.left>0&&prev!==null&&r.left>=prev);prev=r.left;
      if(r.left>0&&r.checked>0&&!stuck){return rvLoad().then(next);}
      say('Проверено страниц: '+t.checked+'. Новых подтверждённых: '+t.confirmed+', уточнено: '+t.corrected+', снято подтверждение (на странице не «Закрыт»): '+t.reverted+
        ', возвратов: '+t.refunded+', не разобрано: '+t.unclear+', оценок прочитано: '+t.stars+'.'+(r.left?' Осталось проверить: '+r.left+' (страницы не разобраны, повтор не поможет).':''),t.unclear>0);
      return rvLoad().then(fin);
    }).catch(function(e){say((t.checked?'Остановилось после '+t.checked+' проверенных страниц. ':'')+e.message,true);rvLoad();fin();});
  })();
}
function rvReadStars(o){return ap('/api/review/read-stars',{id:o.id});}
function rvReadAll(){
  var todo=RV.orders.filter(function(o){return o.reward&&!o.reward.at&&!o.reward.can;}),i=0,got=0;
  if(!todo.length){say('Нет заказов, где награда возможна и оценка ещё не совпала с нужной.');return;}
  if(!confirm('Прочитать оценки по '+todo.length+' заказам? Это '+todo.length+' запросов страниц заказов, по одному с паузой. Ничего не отправляется покупателям.'))return;
  $('rv-readall').disabled=true;
  (function next(){
    if(i>=todo.length){$('rv-readall').disabled=false;say('Готово: оценка найдена у '+got+' из '+todo.length+'.');rvLoad();return;}
    var o=todo[i++];say('Читаю оценки: '+i+' из '+todo.length+'…');
    rvReadStars(o).then(function(r){if(r.stars)got++;next();}).catch(function(e){$('rv-readall').disabled=false;say('Остановился: '+e.message,true);rvLoad();});
  })();
}
function rvRender(){
  var box=$('rv-tbl');box.textContent='';
  if(!RV.orders.length){box.appendChild(el('div','empty','Подтверждённых заказов нет. Нажмите «Найти подтверждённые заказы»: программа откроет страницы заказов и найдёт закрытые.'));return;}
  var t=el('table'),th=el('thead'),hr=el('tr');
  ['Заказ','Лот','Подтверждён','Шаблон','Просьба','Оценка отзыва','Награда','Текст просьбы','Действия'].forEach(function(h){hr.appendChild(el('th','',h));});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  RV.orders.forEach(function(o){
    var tr=el('tr'),c=el('td','id');c.appendChild(ordLink(o.id));tr.appendChild(c);
    tr.appendChild(el('td','',o.lot||'—'));
    var ct=el('td','cnt',o.confirmed_at?o.confirmed_at.replace('T',' ').slice(0,16):'—');
    if(o.confirmed_by)ct.appendChild(el('div','',o.confirmed_by));
    tr.appendChild(ct);
    var kt=el('td','cnt',o.key||'—');
    if(!o.review_at&&!o.reward_in_text)kt.appendChild(el('div','warn','без награды в тексте'));
    tr.appendChild(kt);
    var st=o.review_at?'отправлена '+o.review_at.replace('T',' ').slice(0,16):(o.can?'можно отправить':o.blockers.join('; '));
    tr.appendChild(el('td',o.can||o.review_at?'cnt':'warn cnt',st));
    var sc=el('td'),sel=el('select');[['','—'],['1','1★'],['2','2★'],['3','3★'],['4','4★'],['5','5★']].forEach(function(p){var op=el('option','',p[1]);op.value=p[0];if(String(o.stars||'')===p[0])op.selected=true;sel.appendChild(op);});
    sel.disabled=!!(o.reward&&o.reward.at);sel.title='Запишите оценку после того, как сами посмотрели отзыв на странице заказа';
    sel.addEventListener('change',function(){
      if(sel.value&&!confirm('Подтверждаете: вы сами посмотрели отзыв по заказу #'+o.id+', оценка '+sel.value+' из 5?')){sel.value=String(o.stars||'');return;}
      ap('/api/review/stars',{id:o.id,stars:sel.value}).then(function(){say('');return rvLoad();}).catch(function(e){say(e.message,true);rvLoad();});});
    sc.appendChild(sel);
    if(o.stars&&o.stars_src)sc.appendChild(el('div','cnt',o.stars_src==='site'?'прочитана с сайта':'внесена вручную'));
    tr.appendChild(sc);
    var rw=o.reward,rt=el('td','cnt');
    if(!rw)rt.textContent='—';
    else if(rw.at)rt.textContent='выдана '+rw.at.replace('T',' ').slice(0,16)+(rw.spent?', '+Number(rw.spent).toLocaleString('ru-RU',{maximumFractionDigits:2})+' ₽'+(rw.spent_est?' (по текущей цене)':''):'');
    else if(rw.can)rt.textContent='можно выдать ('+(rw.type==='stock'?rw.units+' шт.':'бонус')+')'+(rw.cost?', ≈'+Number(rw.cost).toLocaleString('ru-RU',{maximumFractionDigits:2})+' ₽':'')+(rw.unrequested?', отзыв без просьбы':'');
    else{rt.textContent=(rw.unrequested?'без просьбы: ':'')+rw.blockers.join('; ');rt.className=(rw.unrequested?'':'warn ')+'cnt';}
    tr.appendChild(rt);
    var tx=el('td','cnt',o.text||'—');tx.style.whiteSpace='pre-wrap';tx.style.maxWidth='320px';tr.appendChild(tx);
    var ac=el('td','btns');
    if(o.can){var b=cfBtn('Отправить просьбу',function(){
      if(!confirm('Отправить покупателю просьбу об отзыве по заказу #'+o.id+'?\n\n'+o.text))return;
      b.disabled=true;rvSend(o).then(function(r){say(r.note);}).catch(function(e){say(e.message,true);rvLoad();});});ac.appendChild(b);}
    if(rw&&rw.can){var g=cfBtn('Выдать награду',function(){
      if(!confirm('Покупатель оставил отзыв на '+o.stars+' из 5 (заказ #'+o.id+'). Отправить ему награду ('+(rw.type==='stock'?rw.units+' шт. из списка':'бонус')+')?'))return;
      g.disabled=true;ap('/api/review/reward-send',{id:o.id}).then(function(r){
        if(!r.sent)throw new Error('Сайт вернул ошибку: '+r.error_site+'. Награда не отмечена выданной, список не тронут.');say(r.note);return rvLoad();}).catch(function(e){say(e.message,true);rvLoad();});});ac.appendChild(g);}
    if((o.review_at||rw)&&!(rw&&rw.at))ac.appendChild(cfBtn('Прочитать оценку',function(){
      rvReadStars(o).then(function(r){say(r.stars?('Оценка по заказу #'+o.id+': '+r.stars+' из 5.'):(r.note||'Оценка не найдена.'),!r.stars&&r.found);return rvLoad();}).catch(function(e){say(e.message,true);});}));
    if(!o.review_at)ac.appendChild(cfBtn(o.skip?'Снять «не просить»':'Не просить',function(){
      ap('/api/review/skip',{id:o.id,off:o.skip}).then(function(){say('');return rvLoad();}).catch(function(e){say(e.message,true);});}));
    tr.appendChild(ac);tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(foldWrap('rv-tbl','Подтверждённые заказы',RV.orders.length,t));
}
function rvLog(rows){
  var box=$('rv-log');box.textContent='';
  if(!rows||!rows.length){box.appendChild(el('div','cnt','Записей нет.'));return;}
  var t=tbl(['Время','Заказ','Действие','Подробности','Результат'],rows.map(function(r){return[r.time.replace('T',' '),'',r.action,r.detail,r.ok?'ок':'отказ'];}));
  Array.prototype.forEach.call(t.querySelectorAll('tbody tr'),function(tr,i){var r=rows[i];if(r&&r.order)tr.children[1].appendChild(ordLink(r.order));});
  fold5(box,'rv-log',t);
}
$('rv-reload').addEventListener('click',function(){
  if(RVS.dirty){if(!confirm('Есть несохранённые правки. Загрузить версию с сервера и отбросить их?'))return;RVS.dirty=false;}
  rvLoad();});
document.addEventListener('visibilitychange',function(){if(!document.hidden&&view==='review'&&!RVS.dirty)rvLoad();});
$('rv-readall').addEventListener('click',rvReadAll);
$('rv-scan').addEventListener('click',rvScan);
$('rv-save').addEventListener('click',function(){rvSave(false);});
$('rv-def').addEventListener('input',rvAuto);
$('rv-delay').addEventListener('input',rvAuto);
$('rv-addrule').addEventListener('click',function(){RV.rules.push(rvNewRule());rvRules();});
$('rv-ins').addEventListener('click',function(){
  var id=$('rv-insid').value.trim();if(!id){say('Введите номер заказа.',true);return;}
  if(!confirm('Открыть одну страницу заказа #'+id.replace('#','')+' и сохранить только блок отзыва (без чата)?'))return;
  $('rv-ins').disabled=true;
  ap('/api/review/inspect-order',{id:id}).then(function(r){$('rv-ins').disabled=false;say('');var o=$('rv-insout');o.style.display='block';
    o.textContent='Сохранено: '+r.path+'\nБлоков: '+r.blocks+'\nКлассы: '+r.classes.join(', ')+'\n\nПришлите мне файл (в нём нет чата, токены вырезаны).';})
   .catch(function(e){$('rv-ins').disabled=false;say(e.message,true);});});
$('rv-all').addEventListener('click',function(){
  var todo=RV.orders.filter(function(o){return o.can;}).slice(0,30);
  if(!todo.length){say('Нет заказов, готовых к отправке.');return;}
  var nop=todo.filter(function(o){return !o.reward_in_text;}).length;
  if(!confirm('Отправить просьбу об отзыве по '+todo.length+' заказам (не больше 30 за раз), по одному сообщению с паузами? Тексты видны в таблице.'+(nop?'\n\nВНИМАНИЕ: в '+nop+' из них про награду ничего не написано (у лота нет правила с наградой, идёт общий шаблон). Отправить всё равно?':'')))return;
  $('rv-all').disabled=true;var i=0,sent=0,skipped=0;
  (function next(){
    if(i>=todo.length){$('rv-all').disabled=false;say('Готово: отправлено '+sent+', отказов проверки '+skipped+'. Проверьте сообщения в диалогах.');rvLoad();return;}
    rvSend(todo[i++]).then(function(){sent++;next();}).catch(function(e){
      if(/^просьба не отправлена/.test(e.message)){skipped++;next();return;}
      $('rv-all').disabled=false;say('Остановился: '+e.message+' (отправлено '+sent+').',true);rvLoad();});
  })();
});

$('rv-rwall').addEventListener('click',function(){
  var todo=RV.orders.filter(function(o){return o.reward&&o.reward.can;}).slice(0,30);
  if(!todo.length){say('Нет заказов, готовых к выдаче награды.');return;}
  if(!confirm('Выдать награду по '+todo.length+' заказам (не больше 30 за раз)? Каждому покупателю уйдёт одно сообщение с наградой, по одному с паузами. У всех оценка совпала с нужной.\n\nЗаказы: '+todo.map(function(o){return '#'+o.id;}).join(', ')))return;
  $('rv-rwall').disabled=true;var i=0,sent=0,skipped=0;
  function fail(m){$('rv-rwall').disabled=false;say('Остановился: '+m+' (выдано '+sent+' из '+todo.length+').',true);rvLoad();}
  (function next(){
    if(i>=todo.length){$('rv-rwall').disabled=false;say('Готово: награда выдана по '+sent+' заказам, отказов проверки '+skipped+' (причины в журнале). Проверьте сообщения в диалогах.',skipped>0);rvLoad();return;}
    var o=todo[i++];say('Выдаю награды: '+i+' из '+todo.length+'…');
    ap('/api/review/reward-send',{id:o.id}).then(function(r){
      if(!r.sent){fail('сайт вернул ошибку по заказу #'+o.id+': '+r.error_site+'. Награда по нему не отмечена выданной');return;}
      sent++;next();}).catch(function(e){if(/^награда не выдана/.test(e.message)){skipped++;next();return;}fail(e.message);});
  })();
});

