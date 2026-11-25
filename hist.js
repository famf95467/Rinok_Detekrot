/* ---------- История ---------- */
var H={d:null,sort:{col:'growth',dir:-1}};
var HF=FP($('h-filters'),function(){var a=[];if(H.d)H.d.days.forEach(function(d){a=a.concat(d.lots);});return a;},function(){recalcHist();});
function hDays(){return H.d.days.map(function(day){var rows=HF.apply(day.lots),sl={};rows.forEach(function(l){sl[l.seller]=1;});return{day:day,rows:rows,st:stats(rows.map(function(l){return l.price;})),sellers:Object.keys(sl).length};});}
function drawChart(box,res){
  box.textContent='';var pts=res.filter(function(r){return r.st;});
  if(!pts.length){box.appendChild(el('div','empty','По этим фильтрам лотов нет ни в один из дней.'));return;}
  var W=760,HH=280,L=62,R=16,T=14,B=40,lo=Infinity,hi=-Infinity,n=res.length;
  pts.forEach(function(r){lo=Math.min(lo,r.st.min);hi=Math.max(hi,r.st.max);});if(hi===lo)hi=lo+1;
  function X(i){return n===1?(L+(W-L-R)/2):L+(W-L-R)*i/(n-1);}function Y(v){return T+(HH-T-B)*(1-(v-lo)/(hi-lo));}
  var s=svg('svg',{viewBox:'0 0 '+W+' '+HH,width:'100%',role:'img'});
  for(var i=0;i<=4;i++){var v=lo+(hi-lo)*i/4,y=Y(v);s.appendChild(svg('line',{x1:L,x2:W-R,y1:y,y2:y,style:'stroke:var(--line)'}));s.appendChild(svg('text',{x:L-6,y:y+4,'text-anchor':'end','font-size':11,style:'fill:var(--mut)'},money(Math.round(v))));}
  var step=Math.ceil(n/8);
  res.forEach(function(r,i){if(i%step===0||i===n-1)s.appendChild(svg('text',{x:X(i),y:HH-B+18,'text-anchor':'middle','font-size':11,style:'fill:var(--mut)'},r.day.date.slice(5)));});
  [['min','Мин','var(--s)','6 4'],['med','Медиана','var(--acc)',''],['max','Макс','var(--n)','2 3']].forEach(function(d){
    var path='',on=false;res.forEach(function(r,i){if(!r.st){on=false;return;}path+=(on?'L':'M')+X(i).toFixed(1)+' '+Y(r.st[d[0]]).toFixed(1)+' ';on=true;});
    var p=svg('path',{d:path,style:'fill:none;stroke:'+d[2]+';stroke-width:'+(d[0]==='med'?2.6:1.8)});if(d[3])p.setAttribute('stroke-dasharray',d[3]);s.appendChild(p);
    res.forEach(function(r,i){if(!r.st)return;var c=svg('circle',{cx:X(i),cy:Y(r.st[d[0]]),r:3.6,style:'fill:'+d[2]});c.appendChild(svg('title',{},r.day.date+': '+d[1]+' '+money(r.st[d[0]])+' ₽'));s.appendChild(c);});});
  box.appendChild(s);box.appendChild(el('div','cnt','Линии: минимум (пунктир), медиана (сплошная), максимум (точки). Цены витрины в ₽, это не сделки.'));
}
function hDiff(box,res,ia,ib){
  box.textContent='';
  if(ia>=ib){box.appendChild(el('div','empty','Выберите первым более ранний день, вторым более поздний.'));return;}
  var A=res[ia].rows,B=res[ib].rows,ma={},mb={};A.forEach(function(l){ma[l.id]=l;});B.forEach(function(l){mb[l.id]=l;});
  var added=B.filter(function(l){return !ma[l.id];}),gone=A.filter(function(l){return !mb[l.id];}),chg=[];
  B.forEach(function(l){var o=ma[l.id];if(o&&o.price!==l.price)chg.push([o,l]);});
  var secn=0;function sec(title,rows,cols,mk,nc,pr){var key='h-diff-'+(++secn);
    box.appendChild(el('h3','',title+': '+rows.length));if(!rows.length){box.appendChild(el('div','cnt','Нет.'));return;}
    var sh=rows.slice().sort(function(x,y){return pr(x)-pr(y);}).slice(0,200);fold5(box,key,tbl(cols,sh.map(mk),nc),rows.length,200);
    if(rows.length>sh.length)box.appendChild(el('div','cnt','Показаны первые 200 из '+rows.length+'.'));}
  var one=function(l){return l.price;};
  sec('Новые лоты',added,['Цена','Продавец','Отзывов','Название'],function(l){return[money(l.price)+' ₽',l.seller,String(l.reviews),l.title];},[0,2],one);
  sec('Пропали',gone,['Была цена','Продавец','Отзывов','Название'],function(l){return[money(l.price)+' ₽',l.seller,String(l.reviews),l.title];},[0,2],one);
  sec('Цена изменилась',chg,['Было','Стало','Разница','Продавец','Название'],function(p){var d=p[1].price-p[0].price;return[money(p[0].price)+' ₽',money(p[1].price)+' ₽',(d>0?'+':'')+money(Math.round(d*100)/100)+' ₽',p[1].seller,p[1].title];},[0,1,2],function(p){return p[1].price;});
}
function hSellers(box,res,ia,ib){
  box.textContent='';if(ia>=ib)return;
  var dayA=H.d.days[ia],dayB=H.d.days[ib],m={},list=[];
  res[ib].rows.forEach(function(l){var s=m[l.seller];if(!s){s=m[l.seller]={seller:l.seller,n:0,min:l.price};list.push(s);}s.n++;if(l.price<s.min)s.min=l.price;});
  list.forEach(function(s){var b=dayB.sellers[s.seller]||[0,''],a=dayA.sellers[s.seller],meta=H.d.meta[s.seller]||{};
    s.reviews=b[0];s.site=b[1];s.growth=a?b[0]-a[0]:null;
    s.nc=meta.fc!==null&&meta.fc!==undefined&&meta.fc>ia;s.nn=!s.nc&&meta.fs!==null&&meta.fs!==undefined&&meta.fs>ia;
    s.tags=(s.nc?'новый в категории':'')+(s.nn?'новый в нише':'');});
  if(!list.length){box.appendChild(el('div','empty','По этим фильтрам продавцов нет.'));return;}
  var cols=[{k:'seller',t:'Продавец'},{k:'n',t:'Лотов',num:1},{k:'min',t:'Мин. цена',num:1},{k:'reviews',t:'Отзывов',num:1},{k:'growth',t:'Прирост отзывов (оценка, не факт)',num:1},{k:'site',t:'На сайте'},{k:'tags',t:'Метка'}],cs=H.sort;
  list.sort(function(x,y){var a=x[cs.col],b=y[cs.col],r;if(a===null||a===undefined)a=(cs.dir>0?Infinity:-Infinity);if(b===null||b===undefined)b=(cs.dir>0?Infinity:-Infinity);
    r=(typeof a==='string')?a.localeCompare(b,'ru'):(a===b?0:(a<b?-1:1));return r*cs.dir||x.min-y.min;});
  var t=el('table'),th=el('thead'),hr=el('tr');
  cols.forEach(function(c){var h=el('th',(c.num?'num ':'')+'srt',c.t+(cs.col===c.k?(cs.dir>0?' ▲':' ▼'):''));
    h.addEventListener('click',function(){H.sort={col:c.k,dir:(cs.col===c.k?-cs.dir:(c.k==='seller'||c.k==='site'||c.k==='tags'?1:-1))};recalcHist();});hr.appendChild(h);});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  list.slice(0,500).forEach(function(s){var tr=el('tr');tr.appendChild(el('td','',s.seller));tr.appendChild(el('td','num',String(s.n)));tr.appendChild(el('td','num',money(s.min)+' ₽'));tr.appendChild(el('td','num',String(s.reviews)));
    tr.appendChild(el('td','num',s.growth===null?'—':((s.growth>0?'+':'')+s.growth)));tr.appendChild(el('td','',s.site));tr.appendChild(el('td','',s.tags));tb.appendChild(tr);});
  t.appendChild(tb);fold5(box,'h-sellers',t,list.length,500);box.appendChild(el('div','cnt','Сравнение: '+dayA.date+' → '+dayB.date+'. «—»: продавца не было на странице в день начала.'));
}
function recalcHist(){
  var d=H.d;if(!d)return;var e=$('h-empty'),body=$('h-body');
  if(d.days.length<2){e.textContent='Мало данных: нужны снимки за два разных дня, сейчас дней: '+d.days.length+'.';e.style.display='block';body.style.display='none';return;}
  e.style.display='none';body.style.display='block';
  var res=hDays(),ia=$('h-a').selectedIndex,ib=$('h-b').selectedIndex;
  $('h-fact').textContent='Дней в истории: '+d.days.length+' (с '+d.days[0].date+' по '+d.days[d.days.length-1].date+'), снимков всего: '+d.snapshots+'. Цены витрины, не сделки.';
  $('h-est').textContent='Что считать скриптом, решают правила и ваши отметки. Прирост отзывов и метки «новый» — оценка.';
  drawChart($('h-chart'),res);
  $('h-days').textContent='';fold5($('h-days'),'h-days',tbl(['День','Снимок','Лотов (в расчёте)','Продавцов','Мин','Медиана','Макс'],res.slice().reverse().map(function(r){var st=r.st;return[r.day.date,r.day.time,String(r.rows.length),String(r.sellers),st?money(st.min)+' ₽':'—',st?money(st.med)+' ₽':'—',st?money(st.max)+' ₽':'—'];}),[2,3,4,5,6]));
  hDiff($('h-diff'),res,ia,ib);hSellers($('h-sellers'),res,ia,ib);
}
function loadHist(){
  return api('/api/history').then(function(d){
    var oa=$('h-a').value,ob=$('h-b').value;H.d=d;
    ['h-a','h-b'].forEach(function(id){var s=$(id);s.textContent='';d.days.forEach(function(x){var o=el('option','',x.date);o.value=x.date;s.appendChild(o);});});
    var n=d.days.length;$('h-a').selectedIndex=Math.max(0,n-2);$('h-b').selectedIndex=Math.max(0,n-1);
    d.days.forEach(function(x,i){if(x.date===oa)$('h-a').selectedIndex=i;if(x.date===ob)$('h-b').selectedIndex=i;});
    HF.list();recalcHist();say('');}).catch(function(e){say(e.message,true);});
}
['h-a','h-b'].forEach(function(id){$(id).addEventListener('change',recalcHist);});

