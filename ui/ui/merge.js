/* ---------- Слияние лотов ---------- */
var MG={lots:[],sel:{}};
function mgLabel(l){return l.title+' · ID '+l.id+' · заказов '+l.orders+(l.last?' · последний '+l.last:'')+(l.in_profile?' · есть в профиле':(l.syn?' · нет в профиле':''));}
function mgCount(){var n=Object.keys(MG.sel).length;$('mg-cnt').textContent=n?('Отмечено старых лотов: '+n):'Ничего не отмечено';}
function mgFill(){
  var q=$('mg-q').value.trim().toLowerCase(),box=$('mg-from');box.textContent='';
  var live={};MG.lots.forEach(function(l){if(!l.into)live[l.id]=1;});Object.keys(MG.sel).forEach(function(k){if(!live[k])delete MG.sel[k];});
  MG.lots.forEach(function(l){
    if(l.into)return;
    var t=mgLabel(l);if(q&&t.toLowerCase().indexOf(q)<0&&!MG.sel[l.id])return;
    var lb=el('label'),c=el('input');c.type='checkbox';c.checked=!!MG.sel[l.id];
    c.addEventListener('change',function(){if(c.checked)MG.sel[l.id]=true;else delete MG.sel[l.id];mgCount();});
    lb.appendChild(c);lb.appendChild(el('span','',' '+t));box.appendChild(lb);});
  var s=$('mg-to'),keep=s.value;s.textContent='';var o0=el('option','','— выберите лот —');o0.value='';s.appendChild(o0);
  MG.lots.forEach(function(l){
    if(l.into)return;
    var t=mgLabel(l);if(q&&t.toLowerCase().indexOf(q)<0&&l.id!==keep)return;
    var o=el('option','',t);o.value=l.id;if(l.id===keep)o.selected=true;s.appendChild(o);});
  mgCount();
}
function mgRender(){
  var byId={};MG.lots.forEach(function(l){byId[l.id]=l;});
  var dn=$('mg-done');dn.textContent='';var merged=MG.lots.filter(function(l){return l.into;});
  if(!merged.length)dn.appendChild(el('div','cnt','Слияний пока нет.'));
  else{var rows=merged.map(function(l){var to=byId[l.into];return[l.title,l.id,String(l.orders),to?to.title:('ID '+l.into),l.into];});
    var t=tbl(['Старый лот','ID','Заказов','Объединён с','ID'],rows,[2]);
    Array.prototype.forEach.call(t.querySelectorAll('tbody tr'),function(tr,i){var l=merged[i],td=el('td','btns'),b=el('button','b','Разъединить');b.type='button';
      b.addEventListener('click',function(){if(!confirm('Разъединить «'+l.title.slice(0,60)+'»? Он снова будет считаться отдельным лотом.'))return;
        ap('/api/stat/v1/lot_unmerge',{from:l.id}).then(function(){say('Лоты разъединены.');mgLoad();}).catch(function(e){say(e.message,true);});});
      td.appendChild(b);tr.appendChild(td);});
    var hr=t.querySelector('thead tr');hr.appendChild(el('th','',''));dn.appendChild(t);}
  var al=$('mg-all');al.textContent='';var q=$('mg-q').value.trim().toLowerCase();
  var sh=MG.lots.filter(function(l){return !q||mgLabel(l).toLowerCase().indexOf(q)>=0;});
  al.appendChild(tbl(['Название','ID','Заказов','Последний заказ','Где виден','Статус'],sh.map(function(l){
    return[l.title,l.id,String(l.orders),l.last||'—',l.in_profile?'профиль':(l.src==='заказы'?(l.syn?'только в заказах (нет в профиле)':'заказы'):l.src),l.into?('объединён с ID '+l.into):''];}),[2]));
}
function mgLoad(){
  return ap('/api/lots/merge_list',{offers:$('mg-offers').checked}).then(function(d){
    MG.lots=d.lots;mgFill();mgRender();
    if(d.offers_error)say(d.offers_error,true);else say('');
    if(!d.lots.length)$('mg-res').textContent='Лотов пока нет: на вкладке «Статистика» нажмите «Загрузить заказы» и «Загрузить детали заказов» или включите галочку «добавить мои лоты с аккаунта».';
  }).catch(function(e){say(e.message,true);});
}
$('mg-load').addEventListener('click',mgLoad);
$('mg-q').addEventListener('input',function(){mgFill();mgRender();});
$('mg-go').addEventListener('click',function(){
  var t=$('mg-to').value,froms=Object.keys(MG.sel).filter(function(k){return k!==t;});
  if(!froms.length||!t){say('Отметьте старые лоты и выберите новый лот.',true);return;}
  var by={};MG.lots.forEach(function(l){by[l.id]=l;});
  var titles={};froms.forEach(function(k){titles[k]=by[k].title;});
  if(!confirm('Объединить в «'+by[t].title.slice(0,70)+'» (ID '+t+') лоты:\n\n'+froms.map(function(k){return '• '+by[k].title.slice(0,70)+' (ID '+k+')';}).join('\n')+'\n\nЗаказы, себестоимость, акция и правила наград старых лотов перейдут к новому.'))return;
  ap('/api/lots/merge',{froms:froms,to:t,from_titles:titles,to_title:by[t].title}).then(function(r){
    MG.sel={};$('mg-res').textContent=r.note||'';say('Лотов объединено: '+r.merged+'.');return mgLoad();}).catch(function(e){say(e.message,true);});
});

