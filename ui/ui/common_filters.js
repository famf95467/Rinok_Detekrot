/* ---------- общие фильтры (Цены и История) ---------- */
function FP(root,getLots,onChange){
  var sel={};
  root.className='filters';
  root.innerHTML='<div class="fg"><div class="fh">Продавец</div><input type="text" data-k="sq" placeholder="Поиск продавца"><div class="slist" data-k="sl"></div><div class="cnt"><span data-k="sc"></span> <button type="button" data-k="scl">Снять выбор</button></div></div>'+
  '<div class="fg"><div class="fh">Отзывов у продавца</div><div class="row"><label>от <input type="number" data-k="rf" min="0"></label><label>до <input type="number" data-k="rt" min="0"></label></div><div class="row"><button type="button" data-k="q50">до 50</button><button type="button" data-k="q500">50–500</button><button type="button" data-k="q501">больше 500</button><button type="button" data-k="qa">любые</button></div></div>'+
  '<div class="fg"><div class="fh">Цена, ₽</div><div class="row"><label>от <input type="number" data-k="pf" min="0"></label><label>до <input type="number" data-k="pt" min="0"></label></div></div>'+
  '<div class="fg"><div class="fh">Показывать</div><label><input type="checkbox" data-k="dup"> без дублей</label><label><input type="checkbox" data-k="cheap"> только самый дешёвый лот продавца</label><label><input type="checkbox" data-k="niche"> без лотов «ниша»</label><div class="row" style="margin-top:8px"><button type="button" data-k="reset">Сбросить фильтры</button></div></div>';
  function g(k){return root.querySelector('[data-k='+k+']');}
  function list(){
    var box=g('sl');box.textContent='';var m={},names=[];
    getLots().forEach(function(l){if(m[l.seller]===undefined){m[l.seller]=0;names.push(l.seller);}m[l.seller]++;});
    names.sort(function(a,b){return a.localeCompare(b,'ru');});
    var q=g('sq').value.trim().toLowerCase(),shown=0,more=0;
    names.forEach(function(nm){if(q&&nm.toLowerCase().indexOf(q)<0)return;if(shown>=300){more++;return;}
      var lb=el('label'),i=el('input');i.type='checkbox';i.checked=!!sel[nm];
      i.addEventListener('change',function(){if(i.checked)sel[nm]=true;else delete sel[nm];txt();onChange();});
      lb.appendChild(i);lb.appendChild(el('span','',' '+nm+' ('+m[nm]+')'));box.appendChild(lb);shown++;});
    if(!shown)box.appendChild(el('div','cnt','Нет продавцов с таким именем.'));
    if(more)box.appendChild(el('div','cnt','Показаны первые 300, уточните поиск.'));
    txt();
  }
  function txt(){var n=Object.keys(sel).length;g('sc').textContent=n?('Выбрано продавцов: '+n):'Не выбраны (показаны все)';}
  function rev(a,b){g('rf').value=a;g('rt').value=b;onChange();}
  ['rf','rt','pf','pt'].forEach(function(k){g(k).addEventListener('input',onChange);});
  ['dup','cheap','niche'].forEach(function(k){g(k).addEventListener('change',onChange);});
  g('sq').addEventListener('input',list);
  g('scl').addEventListener('click',function(){sel={};list();onChange();});
  g('q50').addEventListener('click',function(){rev('0','49');});g('q500').addEventListener('click',function(){rev('50','500');});
  g('q501').addEventListener('click',function(){rev('501','');});g('qa').addEventListener('click',function(){rev('','');});
  g('reset').addEventListener('click',function(){sel={};g('sq').value='';['rf','rt','pf','pt'].forEach(function(k){g(k).value='';});['dup','cheap','niche'].forEach(function(k){g(k).checked=false;});list();onChange();});
  function apply(src){
    var rf=numOrNull(g('rf').value),rt=numOrNull(g('rt').value),pf=numOrNull(g('pf').value),pt=numOrNull(g('pt').value),any=Object.keys(sel).length>0,out=[];
    src.forEach(function(l){if(any&&!sel[l.seller])return;if(rf!==null&&l.reviews<rf)return;if(rt!==null&&l.reviews>rt)return;if(pf!==null&&l.price<pf)return;if(pt!==null&&l.price>pt)return;if(g('niche').checked&&l.niche)return;out.push(l);});
    if(g('cheap').checked){var best={};out.forEach(function(l){var b=best[l.seller];if(!b||l.price<b.price)best[l.seller]=l;});out=out.filter(function(l){return best[l.seller]===l;});}
    if(g('dup').checked){var seen={};out=out.filter(function(l){var k=l.dk+'|'+l.price;if(seen[k])return false;seen[k]=1;return true;});}
    return out;}
  function prune(valid){Object.keys(sel).forEach(function(k){if(!valid[k])delete sel[k];});}
  return{apply:apply,list:list,prune:prune};
}

