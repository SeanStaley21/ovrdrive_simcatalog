(function(){
var CLS=['Formula 1','LMP','GT','NASCAR'],COL={'Formula 1':'#ef4444','LMP':'#f97316','GT':'#00AEEF','NASCAR':'#eab308'};
var OTHER_COL='#9ca3af';
var page=document.getElementById('records-page'),btn=document.getElementById('rec-nav-btn');
if(!page||!btn)return;
var rows=[],loaded=false,ready=null,q='',cf='all',only=false,open={};
function S(x){return String(x==null?'':x);}
function esc(s){return S(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function el(id){return document.getElementById(id);}
function ms(t){
  var m=/^(?:(\d+):)?(\d+(?:\.\d+)?)$/.exec(t.trim());
  return m?((m[1]?+m[1]:0)*60+parseFloat(m[2]))*1000:Infinity;
}
page.innerHTML='<div class="rp-head"><h1 id="rp-title" tabindex="-1">Sim Records</h1><p>Fastest laps set on the OVRDRIVE rigs. Search any track or layout.</p></div>'
+'<div class="rp-bar"><label class="rp-search"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg><input id="rp-q" type="search" placeholder="Search tracks or layouts… try “Spa”" aria-label="Search tracks or layouts" autocomplete="off"><button type="button" class="rp-clear" id="rp-x" aria-label="Clear search">&times;</button></label>'
+'<div class="rp-filters" id="rp-filters"></div></div><div class="rp-meta" id="rp-meta"></div><div class="rp-list" id="rp-list"></div>';
var fl=el('rp-filters');
function chips(){
  var h='<button type="button" class="rp-chip'+(cf==='all'?' on':'')+'" data-c="all" aria-pressed="'+(cf==='all')+'">All classes</button>';
  CLS.forEach(function(c){h+='<button type="button" class="rp-chip'+(cf===c?' on':'')+'" data-c="'+c+'" aria-pressed="'+(cf===c)+'" style="--rc:'+COL[c]+'"><i></i>'+c+'</button>';});
  h+='<span class="rp-sep"></span><button type="button" class="rp-chip'+(only?' on':'')+'" data-only="1" aria-pressed="'+only+'">Has times</button>';
  fl.innerHTML=h;
}
fl.addEventListener('click',function(e){
  var b=e.target.closest('button');if(!b)return;
  if(b.dataset.only)only=!only;else cf=b.dataset.c;
  chips();render();
});
el('rp-q').addEventListener('input',function(){q=this.value.trim().toLowerCase();el('rp-x').style.display=q?'block':'none';render();});
el('rp-x').addEventListener('click',function(){var i=el('rp-q');i.value='';q='';this.style.display='none';i.focus();render();});
function entries(list){
  if(!Array.isArray(list))return [];
  return list.map(function(e){
    e=e&&typeof e==='object'?e:{};
    var t=S(e.time);
    return {driver:S(e.driver),car:S(e.car),cls:S(e.class),time:t,date:S(e.date),ms:ms(t)};
  }).sort(function(a,b){return a.ms<b.ms?-1:a.ms>b.ms?1:0;});
}
function load(){
  return fetch('data/rig-records.json').then(function(r){
    if(!r.ok)throw new Error('rig-records.json '+r.status);
    return r.json();
  }).catch(function(err){
    console.error(err);
    return {};
  }).then(function(R){
    R=R&&typeof R==='object'?R:{};
    Object.keys(R).forEach(function(k){
      if(!Object.prototype.hasOwnProperty.call(window.trackData,k))console.warn('rig-records.json: unknown track key',k);
    });
    Object.keys(window.trackData).forEach(function(k){
      var p=k.split('::'),d=window.trackData[k];
      rows.push({key:k,name:p[0],layout:p[1],country:S(d.country),length:S(d.length),ents:entries(R[k]),hay:(p[0]+' '+p[1]+' '+S(d.country)+' '+S(d.state)).toLowerCase()});
    });
    rows.sort(function(a,b){return a.name.localeCompare(b.name)||a.layout.localeCompare(b.layout);});
    loaded=true;
  });
}
function detail(r){
  var h='',groups=CLS.slice();
  if(cf==='all')r.ents.forEach(function(e){if(CLS.indexOf(e.cls)<0&&groups.indexOf(e.cls)<0)groups.push(e.cls);});
  groups.forEach(function(c){
    var es=r.ents.filter(function(e){return e.cls===c;});
    if(!es.length||(cf!=='all'&&cf!==c))return;
    h+='<div class="rp-cls" style="--rc:'+(COL[c]||OTHER_COL)+'"><h3>'+esc(c||'Other')+'</h3>';
    es.forEach(function(e,i){h+='<div class="rp-ent"><span class="rp-rank">'+(i+1)+'</span><span class="rp-who">'+esc(e.driver)+'</span><span class="rp-time">'+esc(e.time)+'</span><span class="rp-car">'+esc(e.car)+(e.date?' · '+esc(e.date):'')+'</span></div>';});
    h+='</div>';
  });
  if(!h)h='<div class="rp-none">No rig times for this selection</div>';
  if(typeof window.openTrk==='function')h+='<button type="button" class="rp-open" data-open="1">Open track</button>';
  return h;
}
function render(){
  if(!loaded)return;
  var toks=q.split(/\s+/).filter(Boolean);
  var list=rows.filter(function(r){
    if(toks.some(function(t){return r.hay.indexOf(t)<0;}))return false;
    if(cf!=='all'&&!r.ents.some(function(e){return e.cls===cf;}))return false;
    if(only&&!r.ents.length)return false;
    return true;
  });
  var withT=rows.filter(function(r){return r.ents.length;}).length;
  el('rp-meta').innerHTML='<span><b>'+list.length+'</b> layout'+(list.length===1?'':'s')+'</span><span>'+withT+' of '+rows.length+' have rig times</span>';
  var box=el('rp-list');
  if(!list.length){var fs=[];if(q)fs.push('“'+esc(q)+'”');if(cf!=='all')fs.push(cf+' times');if(only)fs.push('rig times');box.innerHTML='<div class="rp-empty">No tracks match '+(fs.join(' + ')||'this search')+'.'+((cf!=='all'||only)?'<br><button type="button" class="rp-open" id="rp-reset" style="margin-top:14px">Clear filters</button>':'')+'</div>';var rb=el('rp-reset');if(rb)rb.onclick=function(){cf='all';only=false;chips();render();};return;}
  var h='';
  list.forEach(function(r){
    var sub=(r.layout.toLowerCase()!==r.name.toLowerCase()?r.layout+' · ':'')+[r.country,r.length].filter(Boolean).join(' · ');
    var right;
    if(!r.ents.length)right='<span class="rp-none">No rig time yet</span>';
    else if(cf!=='all'){var b=r.ents.filter(function(e){return e.cls===cf;})[0];right='<span class="rp-best">'+esc(b.time)+'</span><span class="rp-count">'+esc(b.driver)+'</span>';}
    else{var cs=CLS.filter(function(c){return r.ents.some(function(e){return e.cls===c;});});right='<span class="rp-dots">'+cs.map(function(c){return '<i style="--rc:'+COL[c]+'" title="'+c+'"></i>';}).join('')+'</span><span class="rp-count">'+r.ents.length+' time'+(r.ents.length===1?'':'s')+'</span>';}
    h+='<div class="rp-item'+(open[r.key]?' open':'')+'" data-k="'+esc(r.key)+'"><button type="button" class="rp-row" aria-expanded="'+(open[r.key]?'true':'false')+'"><span class="rp-name"><b>'+esc(r.name)+'</b><span>'+esc(sub)+'</span></span><span class="rp-right">'+right+'</span><span class="rp-chev"></span></button><div class="rp-detail">'+(open[r.key]?detail(r):'')+'</div></div>';
  });
  box.innerHTML=h;
}
el('rp-list').addEventListener('click',function(e){
  var it=e.target.closest('.rp-item');if(!it)return;
  var r=rows.filter(function(x){return x.key===it.dataset.k;})[0];if(!r)return;
  if(e.target.closest('[data-open]')){
    var cats=window._trackToCat&&window._trackToCat[r.name];
    if(cats&&window.openTrk)window.openTrk(r.name,cats[0],r.layout);
    return;
  }
  if(!e.target.closest('.rp-row'))return;
  var o=!it.classList.contains('open');open[r.key]=o;
  it.classList.toggle('open',o);it.querySelector('.rp-row').setAttribute('aria-expanded',o);
  it.querySelector('.rp-detail').innerHTML=o?detail(r):'';
});
function isOpen(){return page.style.display==='block';}
function activateTab(){
  document.querySelectorAll('.top-tab').forEach(function(t){t.classList.toggle('active',t.dataset.page===window.activePage);});
}
function show(){
  if(isOpen())return;
  if(!window.trackData||typeof window.writeHash!=='function')return;
  el('landing').style.display='none';el('page-layout').style.display='none';el('top-tabs').style.display='';
  document.querySelectorAll('.top-tab').forEach(function(t){t.classList.remove('active');});
  page.style.display='block';
  btn.classList.add('active');btn.setAttribute('aria-pressed','true');
  refreshCompare();
  writeHash();
  chips();
  if(!ready)ready=load();
  ready.then(render);
  window.scrollTo(0,0);
  el('rp-title').focus({preventScroll:true});
}
function hide(){
  if(!isOpen())return;
  page.style.display='none';
  btn.classList.remove('active');btn.setAttribute('aria-pressed','false');
  el('page-layout').style.display='';
  activateTab();
  refreshCompare();
}
btn.setAttribute('aria-pressed','false');
btn.addEventListener('click',show);
document.querySelectorAll('.top-tab').forEach(function(t){t.addEventListener('click',hide);});
window.RigRecords={show:show,hide:hide,isOpen:isOpen};
})();
