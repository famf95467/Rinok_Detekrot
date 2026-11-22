/* ---------- Главная ---------- */
/* Только чтение: берёт данные из уже существующих маршрутов (автопилот, заказы, статистика, статистика v1, подтверждения). Единственное действие: включить/выключить автопилот. */
var HM={expand:false,items:[],busy:false};
function hmRub(v){if(v===null||v===undefined||v==='')return '—';return money(v).replace(/^-/,'−')+' ₽';}
function hmDate(s){return String(s||'').replace(/^\d{4}-(\d\d)-(\d\d).*$/,'$2.$1');}
function hmTime(s){return String(s||'').slice(11,16);}
function hmNice(x){var p=Math.pow(10,Math.floor(Math.log(x)/Math.LN10)),f=x/p;return(f<=1?1:f<=2?2:f<=5?5:10)*p;}
function hmDays(n,one,few,many){var a=n%100,b=n%10;return n+' '+((a>10&&a<15)?many:(b===1?one:(b>1&&b<5?few:many)));}

function hmAttention(st,sr,r7,cf){
  var out=[];
  if(st){
    (st.attention||[]).forEach(function(a){
      var k=a.kind,tab='auto',btn='Открыть автопилот';
      if(k==='key'){tab='acc';btn='Открыть аккаунт';}
      else if(k==='ticket'){tab='confirm';btn='Открыть заказы';}
      else if(k==='stock'){tab='review';btn='Открыть отзывы';}
      out.push({crit:k!=='ticket'&&k!=='stock',title:a.text,sub:'',btn:btn,tab:tab,pri:k==='key'||k==='lock'?0:1});
    });
    (st.steps||[]).filter(function(x){return !x.ok;}).forEach(function(x){
      out.push({crit:true,title:'Ошибка автопилота в последнем цикле',sub:x.name+': '+x.text,btn:'Открыть журнал',tab:'auto',pri:1});
    });
  }
  if(cf&&cf.ready>0)out.push({crit:false,title:'Заказы готовы к тикету: '+cf.ready,sub:'Покупатель не подтвердил заказ, условия для тикета выполнены',btn:'Открыть заказы',tab:'confirm',pri:2});
  if(sr&&r7){
    var t=sr.tot,all=t.closed+t.paid+t.refund,lim=r7.settings&&r7.settings.max_refund_pct;
    if(all>=5&&lim!==undefined&&t.refund/all*100>lim)
      out.push({crit:false,title:'Высокая доля возвратов: '+Math.round(t.refund/all*100)+' % за 30 дней',sub:'Порог в настройках статистики v1: '+lim+' %',btn:'Показать возвраты',tab:'stats',pri:3});
  }
  out.sort(function(a,b){return (b.crit-a.crit)||(a.pri-b.pri);});
  return out;
}
function hmStatus(items,nodata){
  var box=$('hm-status');box.textContent='';
  box.className='hm-status'+(items.length||nodata?'':' ok');
  if(nodata){box.appendChild(el('div','hm-t','Нет данных для проверки'));return;}
  if(!items.length){box.appendChild(el('div','hm-t','Всё в порядке'));return;}
  box.appendChild(el('div','hm-t','Требует внимания: '+items.length));
  (HM.expand?items:items.slice(0,3)).forEach(function(x){
    var row=el('div','hm-item'),d=el('div','d'),dot=el('span','hm-dot '+(x.crit?'r':'y'));dot.style.marginRight='8px';
    d.appendChild(dot);d.appendChild(document.createTextNode(x.title));
    if(x.sub)d.appendChild(el('span','s2',x.sub));
    row.appendChild(d);
    var b=el('button',x.crit?'p':'',x.btn);b.type='button';b.addEventListener('click',function(){show(x.tab);});row.appendChild(b);
    box.appendChild(row);
  });
  if(items.length>3){
    var r=el('div','hm-item'),a=el('a','ol',HM.expand?'Свернуть':'Ещё '+(items.length-3));a.href='#';
    a.addEventListener('click',function(e){e.preventDefault();HM.expand=!HM.expand;hmStatus(items,false);});
    r.appendChild(a);box.appendChild(r);
  }
  box.appendChild(el('div','legend','Критичные (ключ, блокировка сессии, ошибка автопилота) всегда выше.'));
}
function hmPill(st){
  var dot=$('hm-dot'),txt=$('hm-pilot'),tg=$('hm-toggle');
  if(!st){dot.className='hm-dot r';txt.textContent='Нет данных об автопилоте';tg.style.display='none';return;}
  var c=st.cfg,bad=st.locked||st.paused||!st.logged;
  dot.className='hm-dot '+(bad?'r':(c.enabled?'':'y'));
  txt.textContent=(st.locked?'Сессия заблокирована':(!st.logged?'Нет входа в аккаунт':(st.paused?'Отправки на паузе':(c.enabled?'Автопилот работает':'Автопилот выключен'))))
    +(st.running?' · идёт цикл':(st.ended?' · последний цикл '+hmTime(st.ended):''));
  tg.style.display='inline-block';tg.textContent=c.enabled?'Выключить автопилот':'Включить автопилот';tg.setAttribute('data-on',c.enabled?'1':'0');
}
function hmTile(label,badge,value,sub,small){
  var t=el('div','hm-tile'),l=el('div','sl',label);
  if(badge){var b=el('span','lab '+(badge==='факт'?'f':'o'),badge);b.style.marginLeft='8px';l.appendChild(b);}
  t.appendChild(l);var v=el('div','hm-v',value);if(small)v.style.fontSize='22px';t.appendChild(v);t.appendChild(el('div','cnt',sub));return t;
}
function hmTiles(st,sr,r7){
  var box=$('hm-tiles');box.textContent='';
  if(r7){
    var nc=(r7.warnings||[]).some(function(w){return /Себестоимость не задана/.test(w);});
    box.appendChild(hmTile('Прибыль, 7 дней','оценка',hmRub(r7.tot.net),nc?'себестоимость задана не у всех лотов':'после всех расходов'));
  }else box.appendChild(hmTile('Прибыль, 7 дней','оценка','—','нет данных'));
  if(sr)box.appendChild(hmTile('Ждёт подтверждения','факт',hmRub(sr.tot.pending),hmDays(sr.tot.paid,'заказ','заказа','заказов')+' за 30 дней'));
  else box.appendChild(hmTile('Ждёт подтверждения','факт','—','нет данных'));
  if(sr)box.appendChild(hmTile('Возвраты, 30 дней','факт',sr.tot.refund+' шт.',hmRub(sr.tot.refund_sum)));
  else box.appendChild(hmTile('Возвраты, 30 дней','факт','—','нет данных'));
  if(st){
    var on=st.cfg.enabled&&!st.paused&&!st.locked;
    var v=el('div','hm-v');v.style.fontSize='22px';var d=el('span','hm-dot'+(on?'':(st.locked||st.paused?' r':' y')));d.style.marginRight='8px';v.appendChild(d);v.appendChild(document.createTextNode(on?'Включён':(st.cfg.enabled?'Остановлен':'Выключен')));
    var t=el('div','hm-tile');t.appendChild(el('div','sl','Автопилот'));t.appendChild(v);t.appendChild(el('div','cnt',st.ended?'последний цикл '+hmTime(st.ended):'цикл ещё не выполнялся'));box.appendChild(t);
  }else box.appendChild(hmTile('Автопилот','','—','нет данных',true));
}
function hmChart(sr){
  var box=$('hm-chart'),daily=sr&&sr.daily;box.textContent='';
  var h=el('div','sl','Выручка за 14 дней'),b=el('span','lab f','факт');b.style.marginLeft='8px';h.appendChild(b);box.appendChild(h);
  if(!daily||!daily.some(function(d){return d.rev>0;})){box.appendChild(el('div','empty','Закрытых заказов за 14 дней нет. Если заказы не загружены: «Статистика» → «Загрузить заказы».'));return;}
  var W=420,H=190,L=44,R=410,T=20,B=165,n=daily.length;
  var max=Math.max.apply(null,daily.map(function(d){return d.rev;})),step=hmNice(max/3),top=step*3;
  function X(i){return L+10+i*(R-L-20)/(n-1);}function Y(v){return B-(B-T)*v/top;}
  var s=svg('svg',{viewBox:'0 0 '+W+' '+H,width:'100%',role:'img','aria-label':'Выручка за 14 дней'});
  for(var k=0;k<=3;k++){var y=Y(step*k);
    s.appendChild(svg('line',{x1:L-8,x2:R,y1:y,y2:y,stroke:'rgba(255,255,255,.08)'}));
    s.appendChild(svg('text',{x:L-12,y:y+4,fill:'#9a9db3','font-size':10,'text-anchor':'end'},money(step*k)));}
  s.appendChild(svg('polyline',{fill:'none',stroke:'#9a7df5','stroke-width':2.4,'stroke-linejoin':'round',points:daily.map(function(d,i){return X(i).toFixed(1)+','+Y(d.rev).toFixed(1);}).join(' ')}));
  daily.forEach(function(d,i){
    var last=i===n-1,c=svg('circle',{cx:X(i).toFixed(1),cy:Y(d.rev).toFixed(1),r:last?3.6:7,fill:last?'#9a7df5':'transparent'});
    c.appendChild(svg('title',{},hmDate('2000-'+d.date)+': '+money(d.rev)+' ₽, заказов '+d.n));s.appendChild(c);});
  [0,Math.floor((n-1)/2),n-1].forEach(function(i){s.appendChild(svg('text',{x:X(i),y:182,fill:'#9a9db3','font-size':10,'text-anchor':'middle'},hmDate('2000-'+daily[i].date)));});
  box.appendChild(s);
  if(sr.updated)box.appendChild(el('div','cnt','Заказы загружены: '+sr.updated.replace('T',' ').slice(0,16)));
}
function hmLots(r7){
  var box=$('hm-lots');box.textContent='';
  if(!r7){box.appendChild(el('div','empty','Нет данных по лотам.'));return;}
  var rows=r7.lots||[];
  if(!rows.length){box.appendChild(el('div','empty','За 7 дней заказов нет (или заказы не загружены на вкладке «Статистика»).'));return;}
  var order=['масштабировать','убрать акцию','поднять цену','понизить цену'],cls={'масштабировать':'v-up','поднять цену':'v-mid','убрать акцию':'v-dn','понизить цену':'v-no'};
  var tips={};(r7.tips||[]).forEach(function(x){(tips[x.lot]=tips[x.lot]||[]).push(x);});
  var t=el('table'),th=el('thead'),hr=el('tr');
  [['Лот',0],['Заказов, 7 дн.',1],['Прибыль (о)',1],['Акция',0],['Вердикт (о)',0]].forEach(function(c){hr.appendChild(el('th',c[1]?'num':'',c[0]));});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  rows.slice(0,8).forEach(function(x){
    var tr=el('tr');tr.appendChild(el('td','',x.title));
    tr.appendChild(el('td','num',String(x.closed+x.paid)));tr.appendChild(el('td','num',hmRub(x.profit)));
    var tp=el('td');if(x.promo&&x.promo.since)tp.appendChild(el('span','hm-promo','акция'));else tp.textContent='—';tr.appendChild(tp);
    var tv=el('td'),ts=(x.id&&tips[x.id])||[];
    if(!ts.length){tv.textContent='—';tv.className='hm-no';}
    else{ts.sort(function(a,b){return order.indexOf(a.action)-order.indexOf(b.action);});
      ts.forEach(function(a,i){var sp=el('span',cls[a.action]||'',(i?' · ':'')+a.action.charAt(0).toUpperCase()+a.action.slice(1));sp.title=a.basis;tv.appendChild(sp);});}
    tr.appendChild(tv);tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(t);
  if(rows.length>8)box.appendChild(el('div','cnt','Показаны 8 из '+rows.length+', полный список на вкладке «Статистика».'));
}
function hmEvents(st){
  var box=$('hm-ev');box.textContent='';
  var log=st&&st.log||[];
  if(!log.length){box.appendChild(el('div','empty','Журнал автопилота пока пуст.'));return;}
  var first=String(log[0].time).slice(0,10);
  log.slice(0,8).forEach(function(x){
    var r=el('div','hm-ev'),d=String(x.time).slice(0,10),tm=el('time','',(d!==first?hmDate(d)+' ':'')+hmTime(x.time));
    r.appendChild(tm);r.appendChild(el('div',x.ok?'':'warn',(x.ok?'':'(!) ')+x.step+': '+x.text));box.appendChild(r);});
}
function homeLoad(){
  if(HM.busy)return Promise.resolve();HM.busy=true;
  function safe(p){return p.catch(function(){return null;});}
  return Promise.all([safe(api('/api/autopilot/status')),safe(ap('/api/stat/report',{days:30})),safe(ap('/api/stat/v1/report',{days:7})),safe(api('/api/confirm/list'))]).then(function(a){
    HM.busy=false;var st=a[0],sr=a[1],r7=a[2],cf=a[3];
    HM.items=hmAttention(st,sr,r7,cf);
    hmPill(st);hmStatus(HM.items,!st&&!sr&&!r7&&!cf);hmTiles(st,sr,r7);hmChart(sr);hmLots(r7);hmEvents(st);
    if(!st&&!sr&&!r7&&!cf)say('Не удалось получить данные для главной. Проверьте, что программа работает.',true);
  });
}
$('hm-refresh').addEventListener('click',function(){homeLoad();});
$('hm-toggle').addEventListener('click',function(){
  var on=$('hm-toggle').getAttribute('data-on')==='1';
  if(!on&&!confirm('Включить автопилот? Он начнёт работать по настройкам вкладки «Автопилот» (какие отправки включены, там же).'))return;
  ap('/api/autopilot/settings',{enabled:!on}).then(function(){say(on?'Автопилот выключен.':'Автопилот включён.');return homeLoad();}).catch(function(e){say(e.message,true);});
});
setInterval(function(){if(view==='home')homeLoad();},60000);
