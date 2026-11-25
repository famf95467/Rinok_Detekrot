/* ---------- Слияние лотов ---------- */
var MG={lots:[],loaded:false,at:0,sel:{},to:'',sort:{a:{col:'last',dir:-1},b:{col:'last',dir:-1}},all:false};
var MG_COLS=[['title','Название'],['id','ID'],['orders','Заказов'],['last','Последний заказ']];
function mgMatch(l){var q=$('mg-q').value.trim().toLowerCase();return !q||(l.title+' '+l.id).toLowerCase().indexOf(q)>=0;}
function mgSorted(key,rows){
  var c=MG.sort[key];
  return rows.slice().sort(function(x,y){
    var a=x[c.col],b=y[c.col],r;
    if(c.col==='orders')r=a-b;else r=String(a||'').localeCompare(String(b||''),'ru');
    return r*c.dir||(x.orders-y.orders);});
}
function mgList(key,boxId,rows,pick,empty){
  var box=$(boxId);box.textContent='';
  if(!rows.length){box.appendChild(el('div','empty',empty));return;}
  var cur=MG.sort[key],t=el('table'),th=el('thead'),hr=el('tr');
  hr.appendChild(el('th','',''));
  MG_COLS.forEach(function(c){
    var h=el('th',(c[0]==='orders'?'num ':'')+'srt',c[1]+(cur.col===c[0]?(cur.dir>0?' ▲':' ▼'):''));h.title='Сортировать';
    h.addEventListener('click',function(){MG.sort[key]={col:c[0],dir:(cur.col===c[0]?-cur.dir:(c[0]==='orders'||c[0]==='last'?-1:1))};mgRender();});
    hr.appendChild(h);});
  th.appendChild(hr);t.appendChild(th);var tb=el('tbody');
  mgSorted(key,rows).forEach(function(l){
    var tr=el('tr'),td=el('td'),i=el('input');
    if(pick==='to'){i.type='radio';i.name='mg-to';i.checked=(MG.to===l.id);i.addEventListener('change',function(){MG.to=l.id;});}
    else{i.type='checkbox';i.checked=!!MG.sel[l.id];i.addEventListener('change',function(){if(i.checked)MG.sel[l.id]=true;else delete MG.sel[l.id];});}
    td.appendChild(i);tr.appendChild(td);
    tr.appendChild(el('td','',l.title));tr.appendChild(el('td','id',l.id));tr.appendChild(el('td','num',String(l.orders)));tr.appendChild(el('td','',l.last||'—'));
    tb.appendChild(tr);});
  t.appendChild(tb);box.appendChild(t);
}
function mgRender(){
  var ok=MG.loaded,live=MG.lots.filter(function(l){return !l.into&&mgMatch(l);});
  Object.keys(MG.sel).forEach(function(k){if(!MG.lots.some(function(l){return l.id===k&&!l.into;}))delete MG.sel[k];});
  if(MG.to&&!MG.lots.some(function(l){return l.id===MG.to&&!l.into;}))MG.to='';
  var A=live.filter(function(l){return l.in_profile;}),B=live.filter(function(l){return !l.in_profile&&l.orders>0;});
  mgList('a','mg-a',ok?A:[],'to',ok?'В профиле лотов нет (или ничего не найдено по поиску).':'Список профиля не загружен: войдите на вкладке «Аккаунт» и нажмите «Обновить список».');
  mgList('b','mg-b',ok?B:[],'from',ok?'Таких лотов нет (или ничего не найдено по поиску).':'Нужен список профиля, чтобы понять, каких лотов в нём уже нет.');
  var dn=$('mg-done');dn.textContent='';
  var byId={};MG.lots.forEach(function(l){byId[l.id]=l;});
  var merged=MG.lots.filter(function(l){return l.into;});
  if(!merged.length){dn.appendChild(el('div','cnt','Слияний пока нет.'));return;}
  var shown=MG.all?merged:merged.slice(0,5);
  var rows=shown.map(function(l){var to=byId[l.into];return[l.title,l.id,String(l.orders),to?to.title:('ID '+l.into),l.into];});
  var t=tbl(['Старый лот','ID','Заказов','Объединён с','ID'],rows,[2]);
  Array.prototype.forEach.call(t.querySelectorAll('tbody tr'),function(tr,i){var l=shown[i],td=el('td','btns'),b=el('button','b','Разъединить');b.type='button';
    b.addEventListener('click',function(){if(!confirm('Разъединить «'+l.title.slice(0,60)+'»? Он снова будет считаться отдельным лотом.'))return;
      ap('/api/stat/v1/lot_unmerge',{from:l.id}).then(function(){say('Лоты разъединены.');mgLoad(true);}).catch(function(e){say(e.message,true);});});
    td.appendChild(b);tr.appendChild(td);});
  t.querySelector('thead tr').appendChild(el('th','',''));dn.appendChild(t);
  if(merged.length>5){var tg=el('button','','');tg.type='button';tg.textContent=MG.all?'Свернуть до 5 строк':'Показать все ('+merged.length+')';
    tg.addEventListener('click',function(){MG.all=!MG.all;mgRender();});dn.appendChild(tg);}
}
function mgLoad(force){
  if(force!==true&&MG.loaded&&Date.now()-MG.at<300000){mgRender();return Promise.resolve();}   /* профиль заново не запрашиваем чаще раза в 5 минут */
  return ap('/api/lots/merge_list',{offers:$('mg-offers').checked}).then(function(d){
    MG.lots=d.lots;MG.loaded=!!d.profile_loaded;MG.at=Date.now();mgRender();
    if(d.offers_error)say(d.offers_error,true);else say('');
    if(!d.lots.length)$('mg-res').textContent='Лотов пока нет: на вкладке «Статистика» нажмите «Загрузить заказы» и «Загрузить детали заказов» или войдите в аккаунт.';
  }).catch(function(e){say(e.message,true);});
}
$('mg-load').addEventListener('click',function(){mgLoad(true);});
$('mg-offers').addEventListener('change',function(){mgLoad(true);});
$('mg-q').addEventListener('input',mgRender);
$('mg-go').addEventListener('click',function(){
  var t=MG.to,froms=Object.keys(MG.sel).filter(function(k){return k!==t;});
  if(!froms.length||!t){say('Отметьте старые лоты (второй список) и выберите новый лот (первый список).',true);return;}
  var by={};MG.lots.forEach(function(l){by[l.id]=l;});
  var titles={};froms.forEach(function(k){titles[k]=by[k].title;});
  if(!confirm('Объединить в «'+by[t].title.slice(0,70)+'» (ID '+t+') лоты:\n\n'+froms.map(function(k){return '• '+by[k].title.slice(0,70)+' (ID '+k+')';}).join('\n')+'\n\nЗаказы, себестоимость, акция и правила наград старых лотов перейдут к новому.'))return;
  ap('/api/lots/merge',{froms:froms,to:t,from_titles:titles,to_title:by[t].title}).then(function(r){
    MG.sel={};MG.to='';$('mg-res').textContent=r.note||'';say('Лотов объединено: '+r.merged+'.');return mgLoad(true);}).catch(function(e){say(e.message,true);});
});
