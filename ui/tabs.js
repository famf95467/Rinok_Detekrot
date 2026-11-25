/* ---------- вкладки ---------- */
var nav=$('nav');
var NAMES={},GOF={home:'Добро пожаловать'};TABS.forEach(function(t){NAMES[t[0]]=t[1];});
{var hb=el('button','tab',NAMES.home);hb.type='button';hb.id='tab-home';hb.addEventListener('click',function(){show('home');});nav.appendChild(hb);}
var GROUPS=[['Заказы',['confirm','remind','review','chat']],['Деньги',['stats','sales']],['Лоты',['acc','merge']],['Рынок',['spy','marks','prices','data','hist']],['Система',['auto']],['Плагины',['plugins']]];
var GCOL={'Заказы':'#9a7df5','Деньги':'#7fd3a0','Лоты':'#e8c070','Рынок':'#6fb3f2','Система':'#f08a8a','Плагины':'#d98ae8'},GEL={};
function gsave(){try{var o={};Object.keys(GEL).forEach(function(k){o[k]=GEL[k].classList.contains('open');});localStorage.setItem('nav_groups',JSON.stringify(o));}catch(e){}}
function gset(name,open){var g=GEL[name];if(!g)return;g.classList.toggle('open',open);g.firstChild.setAttribute('aria-expanded',open?'true':'false');}
GROUPS.forEach(function(g){
  var wrap=el('div','grp open'),head=el('button','gh'),inner=el('div','gin'),box=el('div','gbox');
  head.type='button';head.setAttribute('aria-expanded','true');wrap.style.setProperty('--gc',GCOL[g[0]]||'var(--acc)');
  head.appendChild(el('span','garr','▸'));head.appendChild(el('span','gname',g[0]));
  head.addEventListener('click',function(){gset(g[0],!wrap.classList.contains('open'));gsave();});
  wrap.appendChild(head);box.appendChild(inner);wrap.appendChild(box);GEL[g[0]]=wrap;nav.appendChild(wrap);
  g[1].forEach(function(id){GOF[id]=g[0];var b=el('button','tab',NAMES[id]);b.type='button';b.id='tab-'+id;b.addEventListener('click',function(){show(id);});inner.appendChild(b);});});
try{var gs=JSON.parse(localStorage.getItem('nav_groups')||'{}');Object.keys(gs).forEach(function(k){if(gs[k]===false)gset(k,false);});}catch(e){}
function show(v){
  view=v;if(GOF[v]&&GEL[GOF[v]]&&!GEL[GOF[v]].classList.contains('open')){gset(GOF[v],true);gsave();}document.body.classList.toggle('on-home',v==='home');$('eb').textContent=GOF[v]||'';$('ptitle').textContent=NAMES[v]||'';
  TABS.forEach(function(t){$('v-'+t[0]).style.display=(t[0]===v)?'block':'none';$('tab-'+t[0]).className='tab'+(t[0]===v?' cur':'');});
  $('bar-snap').style.display=(v==='marks'||v==='prices')?'flex':'none';
  if(v==='home')homeLoad();if(v==='spy')spyLoad();if(v==='prices')loadPrices();if(v==='data')loadData();if(v==='hist')loadHist();if(v==='acc')loadAcc();
  if(v==='chat')needLogin('ch',chatList);if(v==='remind')needLogin('rm',function(){});if(v==='confirm')cfLoad();if(v==='review')rvLoad();if(v==='auto'){apLoad(true);tgLoad();}if(v==='merge')mgLoad();if(v==='plugins')plLoad();if(v==='sales')msLoad(true);if(v==='stats')needLogin('st',function(){stReport();sv1All();});
  try{history.replaceState(null,'','#'+v);}catch(e){}
}
function refresh(){load($('snap').value).then(function(){if(view==='prices')loadPrices();});}
$('snap').addEventListener('change',refresh);$('reload').addEventListener('click',refresh);
Array.prototype.forEach.call(document.getElementsByName('f'),function(r){r.addEventListener('change',function(){filter=this.value;render();});});
$('quit').addEventListener('click',function(){
  if(!confirm('Выключить программу? Отметки уже сохранены.'))return;
  ap('/api/quit').then(function(){document.body.textContent='Программа выключена. Эту вкладку можно закрыть.';}).catch(function(e){say(e.message,true);});
});

