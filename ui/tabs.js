/* ---------- вкладки ---------- */
var nav=$('nav');
TABS.forEach(function(t){var b=el('button','tab',t[1]);b.type='button';b.id='tab-'+t[0];b.addEventListener('click',function(){show(t[0]);});nav.appendChild(b);});
function show(v){
  view=v;
  TABS.forEach(function(t){$('v-'+t[0]).style.display=(t[0]===v)?'block':'none';$('tab-'+t[0]).className='tab'+(t[0]===v?' cur':'');});
  $('bar-snap').style.display=(v==='marks'||v==='prices')?'flex':'none';
  if(v==='prices')loadPrices();if(v==='data')loadData();if(v==='hist')loadHist();if(v==='acc')loadAcc();
  if(v==='chat')needLogin('ch',chatList);if(v==='remind')needLogin('rm',function(){});if(v==='confirm')cfLoad();if(v==='review')rvLoad();if(v==='auto'){apLoad(true);tgLoad();}if(v==='merge')mgLoad();if(v==='sales')msLoad(true);if(v==='stats')needLogin('st',function(){stReport();sv1All();});
  try{history.replaceState(null,'','#'+v);}catch(e){}
}
function refresh(){load($('snap').value).then(function(){if(view==='prices')loadPrices();});}
$('snap').addEventListener('change',refresh);$('reload').addEventListener('click',refresh);
Array.prototype.forEach.call(document.getElementsByName('f'),function(r){r.addEventListener('change',function(){filter=this.value;render();});});
$('quit').addEventListener('click',function(){
  if(!confirm('Выключить программу? Отметки уже сохранены.'))return;
  ap('/api/quit').then(function(){document.body.textContent='Программа выключена. Эту вкладку можно закрыть.';}).catch(function(e){say(e.message,true);});
});

