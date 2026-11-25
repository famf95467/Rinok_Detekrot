/* ---------- Плагины ---------- */
var PLG={cur:null,btns:{}};
function plSetBtns(){for(var k in PLG.btns)PLG.btns[k].textContent=(PLG.cur===k)?'Закрыть панель':'Открыть панель';}
function plClose(){PLG.cur=null;$('pl-panel').textContent='';plSetBtns();}
function plTabName(){return api('/api/plugins/list').then(function(d){var it=d.items||[],nm=it.length===1?(it[0].tab||it[0].name):'';if(!nm)return;NAMES.plugins=nm;var b=$('tab-plugins');if(b)b.textContent=nm;if(view==='plugins')$('ptitle').textContent=nm;}).catch(function(){});}
function plLoad(){
  return api('/api/plugins/list').then(function(d){
    var er=$('pl-errors');er.textContent='';
    d.errors.forEach(function(e){var b=el('div','state bad','Плагин «'+e.dir+'» не загружен: '+e.error);er.appendChild(b);});
    var box=$('pl-list');box.textContent='';
    if(!d.items.length){box.appendChild(el('div','empty','Плагинов нет. Папка: '+d.folder));}
    d.items.forEach(function(p){
      var c=el('div','box');
      c.appendChild(el('div','sv',p.name+' · версия '+p.version+' · '+(p.enabled?'включён':'выключен')));
      c.appendChild(el('div','cnt',p.description));
      var bar=el('div','bar');bar.style.marginTop='8px';
      var t=el('button','',p.enabled?'Выключить':'Включить');t.type='button';
      t.addEventListener('click',function(){
        if(!p.enabled&&!confirm('Включить плагин «'+p.name+'»? Автоотправка в нём всё равно выключена, пока вы не включите её в его настройках.'))return;
        ap('/api/plugins/enable',{id:p.id,enabled:!p.enabled}).then(function(){return plLoad();}).then(function(){if(PLG.cur===p.id)plPanel(p.id);}).catch(function(e){say(e.message,true);});});
      var o=el('button','p',PLG.cur===p.id?'Закрыть панель':'Открыть панель');o.type='button';PLG.btns[p.id]=o;o.addEventListener('click',function(){if(PLG.cur===p.id)plClose();else plPanel(p.id);});
      bar.appendChild(t);bar.appendChild(o);c.appendChild(bar);box.appendChild(c);
    });
  }).catch(function(e){say(e.message,true);});
}
function plAct(id,action,data,done){
  return ap('/api/plugins/action',{id:id,action:action,data:data||{}}).then(function(d){say(d.note||'Готово.');if(done)done();return plPanel(id);}).catch(function(e){say(e.message,true);});
}
function plBtn(id,b){
  var x=el('button','',b.label);x.type='button';
  x.addEventListener('click',function(){if(b.confirm&&!confirm(b.confirm))return;x.disabled=true;plAct(id,b.action,b.data).then(function(){x.disabled=false;});});
  return x;
}
function plMerge(a,b){var o={},k;for(k in a)o[k]=a[k];for(k in b)o[k]=b[k];return o;}
function plSettings(root,d,st){
  var bx=el('div','box'),inputs={};
  if(st.help)bx.appendChild(el('div','cnt',st.help));
  st.fields.forEach(function(f){
    var w=el('div');w.style.marginBottom='8px';var i;
    if(f.type==='bool'){var lb=el('label');i=el('input');i.type='checkbox';i.checked=!!f.value;lb.appendChild(i);lb.appendChild(document.createTextNode(' '+f.label));w.appendChild(lb);}
    else if(f.type==='multi'){
      w.appendChild(el('div','fh',f.label));
      i=el('div','slist');i.style.maxHeight='280px';
      var chosen=f.value||[],opts=f.options||[];
      if(!opts.length)i.appendChild(el('div','cnt','Список пуст. Нажмите «Обновить список лотов» (кнопка ниже) и откройте панель заново.'));
      opts.forEach(function(o){var lb2=el('label');lb2.style.display='block';var cb=el('input');cb.type='checkbox';cb.value=o.v;cb.checked=chosen.indexOf(o.v)>=0;
        lb2.appendChild(cb);lb2.appendChild(document.createTextNode(' '+o.l));i.appendChild(lb2);});
      w.appendChild(i);}
    else{w.appendChild(el('div','fh',f.label));
      if(f.type==='longtext'){i=el('textarea','full');i.rows=3;i.maxLength=1500;}
      else if(f.type==='int'){i=el('input');i.type='number';i.min=f.min;i.max=f.max;i.style.width='90px';}
      else{i=el('input','full');i.type='text';i.maxLength=300;}
      i.value=f.value;w.appendChild(i);}
    inputs[f.key]=[i,f.type];
    if(f.help)w.appendChild(el('div','cnt',f.help));
    bx.appendChild(w);});
  var sv=el('button','p','Сохранить настройки');sv.type='button';
  sv.addEventListener('click',function(){var data={};
    for(var k in inputs){var t=inputs[k];
      if(t[1]==='multi')data[k]=Array.prototype.map.call(t[0].querySelectorAll('input:checked'),function(x){return x.value;});
      else data[k]=t[1]==='bool'?t[0].checked:t[1]==='int'?Number(t[0].value):t[0].value;}
    plAct(d.id,st.action,plMerge(st.data,data));});
  bx.appendChild(sv);
  var bar=el('div','bar');bar.style.marginTop='8px';(st.buttons||[]).forEach(function(b){bar.appendChild(plBtn(d.id,b));});
  if((st.buttons||[]).length)bx.appendChild(bar);
  root.appendChild(bx);
}
function plPanel(id){
  PLG.cur=id;plSetBtns();
  return api('/api/plugins/panel?id='+encodeURIComponent(id)).then(function(d){
    var root=$('pl-panel');root.textContent='';
    root.appendChild(el('h3','',d.name+(d.enabled?'':' (выключен: ничего не делает)')));
    var p=d.panel||{};
    if(p.error)root.appendChild(el('div','state bad',p.error));
    (p.warnings||[]).forEach(function(w){root.appendChild(el('div','state bad',w));});
    if(p.status){root.appendChild(tbl(['Показатель','Значение'],p.status.map(function(r){return [String(r[0]),String(r[1])];})));}
    if(p.settings){root.appendChild(el('h3','','Настройки'));plSettings(root,d,p.settings);}
    (p.blocks||[]).forEach(function(bk){root.appendChild(el('h3','',bk.title));plSettings(root,d,bk);});
    (p.forms||[]).forEach(function(f){
      var bx=el('div','box');bx.appendChild(el('div','sv',f.title));if(f.help)bx.appendChild(el('div','cnt',f.help));
      var ed=f.kind==='editor';
      var i=(f.kind==='longtext'||ed)?el('textarea','full'):el('input','full');
      if(ed){i.rows=14;i.value=f.value||'';i.spellcheck=false;i.style.fontFamily='Consolas,monospace';}
      else if(f.kind==='longtext'){i.rows=4;}else{i.type=f.kind==='secret'?'password':'text';}
      i.autocomplete='off';if(f.label)i.placeholder=f.label;bx.appendChild(i);
      var b=el('button','',f.button);b.type='button';
      b.addEventListener('click',function(){
        if(ed){if(!i.value.trim()&&!confirm('Поле пустое: из списка будут удалены ВСЕ ящики (кроме нужных открытым заказам). Продолжить?'))return;plAct(d.id,f.action,plMerge(f.data,{value:i.value}));return;}
        if(!i.value.trim())return;var v=i.value;i.value='';plAct(d.id,f.action,plMerge(f.data,{value:v}));});
      bx.appendChild(b);root.appendChild(bx);});
    if((p.buttons||[]).length){var bar=el('div','bar');p.buttons.forEach(function(b){bar.appendChild(plBtn(d.id,b));});root.appendChild(bar);}
    (p.tables||[]).forEach(function(t,ti){
      if(!t.rows.length){root.appendChild(el('h3','',t.title));root.appendChild(el('div','empty','Пока пусто.'));return;}
      var tb=el('table'),th=el('thead'),hr=el('tr');t.columns.concat(['']).forEach(function(c){hr.appendChild(el('th','',c));});th.appendChild(hr);tb.appendChild(th);
      var bd=el('tbody');t.rows.forEach(function(r){var tr=el('tr');r.cells.forEach(function(c){
          if(c&&typeof c==='object'&&c.select){
            var td0=el('td'),sl=el('select'),cs=c.select;
            cs.options.forEach(function(o){var op=el('option','',o.l);op.value=o.v;if(o.v===cs.value)op.selected=true;sl.appendChild(op);});
            sl.addEventListener('change',function(){sl.disabled=true;plAct(d.id,cs.action,plMerge(cs.data,{value:sl.value})).then(function(){sl.disabled=false;});});
            td0.appendChild(sl);tr.appendChild(td0);}
          else tr.appendChild(el('td','',String(c)));});
        var td=el('td');r.buttons.forEach(function(b){td.appendChild(plBtn(d.id,b));});tr.appendChild(td);bd.appendChild(tr);});
      tb.appendChild(bd);root.appendChild(foldWrap('pl-'+d.id+'-t'+ti,t.title,t.rows.length,tb));});
    root.appendChild(el('h3','','Журнал плагина'));
    if(!d.log.length)root.appendChild(el('div','empty','Журнал пуст.'));
    else fold5(root,'pl-'+d.id+'-log',tbl(['Время','Итог','Событие'],d.log.map(function(l){return [l.time.replace('T',' '),l.ok?'ок':'ошибка',l.text];})));
  }).catch(function(e){say(e.message,true);});
}
plTabName();
