/* ---------- Отметки ---------- */
function visible(l){return filter==='all'||(filter==='none'?!l.mark:l.mark===filter);}
function counts(){
  var c={none:0,'скрипт':0,'ниша':0,'нет':0},unc=0,r=0,h=0;
  lots.forEach(function(l){c[l.mark||'none']++;if(l.kind==='unc')unc++;if(l.src==='правило')r++;if(l.src==='вручную')h++;});
  $('c-none').textContent='('+c.none+')';$('c-all').textContent='('+lots.length+')';$('c-s').textContent='('+c['скрипт']+')';$('c-n').textContent='('+c['ниша']+')';$('c-x').textContent='('+c['нет']+')';
  var t='Факт со страницы '+(data.date||'без даты')+': лотов на странице '+data.total+', в списке '+lots.length+' (правила не смогли решить: '+unc+'). Решено правилом: '+r+', вручную: '+h+'.';
  if(data.stale)t+=' Отметок в marks.csv без лота в этом списке: '+data.stale+'.';
  $('sum').textContent=t;
}
function paint(tr,l){tr.className=l.mark?'m-'+CLS[l.mark]:'';var bs=tr.querySelectorAll('button.b');for(var i=0;i<bs.length;i++)bs[i].className='b '+CLS[MARKS[i]]+(l.mark===MARKS[i]?' on':'');tr.srcTd.textContent=l.src;}
function setMark(l,tr,m){
  if(l.src==='правило'&&l.mark===m){say('Эта отметка поставлена правилом. Чтобы изменить, нажмите другую кнопку.');return;}
  var send=(l.src==='вручную'&&l.mark===m)?'':m;
  ap('/api/mark',{id:l.id,mark:send}).then(function(){if(send===''){l.mark=l.auto;l.src=l.auto?'правило':'';}else{l.mark=send;l.src='вручную';}paint(tr,l);counts();say('');})
   .catch(function(e){say('Отметка НЕ сохранена: '+e.message,true);});
}
function row(l){
  var tr=el('tr'),td=el('td','btns');
  MARKS.forEach(function(m){var b=el('button','b '+CLS[m],m);b.type='button';b.addEventListener('click',function(){setMark(l,tr,m);});td.appendChild(b);});
  tr.appendChild(td);tr.appendChild(el('td','num',l.price===null?'—':l.price.toLocaleString('ru-RU')+' '+(l.cur||'')));
  tr.appendChild(el('td','',l.seller));tr.appendChild(el('td','num',String(l.reviews)));
  var t=el('td','',l.title);if(l.dup)t.appendChild(el('span','tag','дубль '+l.dup));if(l.auto_issue==='да')t.appendChild(el('span','tag','автовыдача'));
  tr.appendChild(t);tr.srcTd=el('td','cnt');tr.appendChild(tr.srcTd);tr.appendChild(el('td','id',l.id));paint(tr,l);return tr;
}
function render(){
  var body=$('rows');body.textContent='';var n=0;lots.forEach(function(l){if(visible(l)){body.appendChild(row(l));n++;}});
  var e=$('empty');
  if(data.note){e.textContent=data.note;e.style.display='block';}
  else if(!n){e.textContent=(filter==='none'&&lots.length)?'Лотов без отметки нет, все решены.':'В этом фильтре лотов нет.';e.style.display='block';}
  else e.style.display='none';
  counts();
}
function load(snap){
  return api('/api/lots'+(snap?'?snap='+encodeURIComponent(snap):'')).then(function(d){
    data=d;lots=d.lots;var s=$('snap');s.textContent='';
    d.snapshots.forEach(function(x){var o=el('option','',x.name);o.value=x.name;if(x.name===d.snap)o.selected=true;s.appendChild(o);});
    render();say('');}).catch(function(e){say(e.message,true);});
}

