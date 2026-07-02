/* smart-table: componente reutilizável (sort + filtros + agrupar/subtotais + CSV) */
(function(){
function num(v){v=(''+(v||'')).replace(/[^0-9.,-]/g,'').split('.').join('').replace(',','.');var n=parseFloat(v);return isNaN(n)?0:n;}
function txt(td){if(!td)return '';var e=td.querySelector('input,select');if(e){if(e.tagName=='SELECT'){var o=e.options[e.selectedIndex];return o?o.text:e.value;}return e.value;}return td.textContent.trim();}
function fmt(n){return 'R$ '+n.toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});}
function esc(s){return (''+s).replace(/&/g,'&amp;').replace(/</g,'&lt;');}
function init(t){
  var head=t.rows[0];if(!head)return;var cols=[],sumc=null,k;
  for(k=0;k<head.cells.length;k++){var th=head.cells[k];
    var c={i:k,type:th.getAttribute('data-t')||'text',f:th.hasAttribute('data-f'),g:th.hasAttribute('data-g'),sum:th.hasAttribute('data-sum'),nos:th.hasAttribute('data-nosort'),label:th.textContent.trim()};
    cols.push(c);if(c.sum)sumc=c;}
  function cval(r,c){var v=txt(r.cells[c.i]);return c.type=='num'?num(v):v;}
  var src=[];for(k=1;k<t.rows.length;k++){var tr=t.rows[k];if(!tr.classList.contains('skip'))src.push(tr);}
  src.forEach(function(r){r.parentNode.removeChild(r);});
  var st={s:-1,d:1,g:-1,fl:{},q:''};
  var bar=document.createElement('div');bar.className='smartbar';
  var qi=document.createElement('input');qi.placeholder='buscar…';qi.oninput=function(){st.q=qi.value.toLowerCase();qi.classList.toggle('fon',!!qi.value);render();};bar.appendChild(qi);
  cols.forEach(function(c){if(!c.f)return;var seen={},opts=[];src.forEach(function(r){var v=cval(r,c);if(!(v in seen)){seen[v]=1;opts.push(v);}});
    opts.sort();var s=document.createElement('select');var h='<option value="">'+esc(c.label)+': todos</option>';
    opts.forEach(function(v){h+='<option>'+esc(v)+'</option>';});s.innerHTML=h;
    s.onchange=function(){st.fl[c.i]=s.value;s.classList.toggle('fon',!!s.value);render();};bar.appendChild(s);});
  var gables=cols.filter(function(c){return c.g;});
  if(gables.length){var gs=document.createElement('select');var gh='<option value="-1">agrupar: —</option>';
    gables.forEach(function(c){gh+='<option value="'+c.i+'">agrupar: '+esc(c.label)+'</option>';});gs.innerHTML=gh;
    gs.onchange=function(){st.g=parseInt(gs.value);gs.classList.toggle('fon',st.g>=0);render();};bar.appendChild(gs);}
  var cbt=document.createElement('button');cbt.type='button';cbt.textContent='CSV';cbt.className='btn';cbt.onclick=expCsv;bar.appendChild(cbt);
  t.parentNode.insertBefore(bar,t);
  cols.forEach(function(c){if(c.nos)return;var th=head.cells[c.i];th.style.cursor='pointer';
    var sp=document.createElement('span');sp.className='sc';th.appendChild(sp);c.sp=sp;
    th.onclick=function(){st.d=(st.s==c.i?-st.d:1);st.s=c.i;render();};});
  function filt(){return src.filter(function(r){
    if(st.q){var ok=false;for(var j=0;j<cols.length;j++){if((''+txt(r.cells[cols[j].i])).toLowerCase().indexOf(st.q)>=0){ok=true;break;}}if(!ok)return false;}
    for(var key in st.fl){if(st.fl[key]&&(''+cval(r,cols[key]))!==st.fl[key])return false;}return true;});}
  function clr(){var rm=t.querySelectorAll('tr.srow,tr.grouphdr,tr.smarttot');for(var j=rm.length-1;j>=0;j--)rm[j].parentNode.removeChild(rm[j]);}
  function render(){var rows=filt();var sc=st.s>=0?cols[st.s]:null;
    if(sc)rows.sort(function(a,b){var x=cval(a,sc),y=cval(b,sc);return (x<y?-1:x>y?1:0)*st.d;});
    clr();
    if(st.g>=0){var gc=cols[st.g];
      rows.sort(function(a,b){var x=cval(a,gc),y=cval(b,gc);if(x<y)return -1;if(x>y)return 1;return sc?((cval(a,sc)<cval(b,sc)?-1:cval(a,sc)>cval(b,sc)?1:0)*st.d):0;});
      var cur=null,hdr=null,sub=0,cnt=0,first=true;
      rows.forEach(function(r){var gv=cval(r,gc);
        if(first||gv!==cur){if(hdr)fill(hdr,sub,cnt);cur=gv;sub=0;cnt=0;first=false;hdr=document.createElement('tr');hdr.className='grouphdr';hdr._gv=gv;t.appendChild(hdr);}
        if(sumc)sub+=cval(r,sumc);cnt++;r.className='srow';t.appendChild(r);});
      if(hdr)fill(hdr,sub,cnt);}
    else rows.forEach(function(r){r.className='srow';t.appendChild(r);});
    var trf=document.createElement('tr');trf.className='smarttot';var tot=0;if(sumc)rows.forEach(function(r){tot+=cval(r,sumc);});
    var hh='';cols.forEach(function(c){if(c.i==0)hh+='<td class=muted>'+rows.length+' itens</td>';else if(c.sum)hh+='<td style=text-align:right><b>'+fmt(tot)+'</b></td>';else hh+='<td></td>';});
    trf.innerHTML=hh;t.appendChild(trf);
    cols.forEach(function(c){if(c.sp)c.sp.textContent=(st.s==c.i?(st.d>0?'▲':'▼'):'');});}
  function fill(hdr,sub,cnt){hdr.innerHTML='<td colspan="'+cols.length+'"><b>'+esc(hdr._gv||'—')+'</b> <span class=tag>'+cnt+' itens'+(sumc?' · '+fmt(sub):'')+'</span></td>';}
  function expCsv(){var rows=filt();var L=[cols.map(function(c){return '"'+c.label+'"';}).join(',')];
    rows.forEach(function(r){L.push(cols.map(function(c){return '"'+(''+txt(r.cells[c.i])).replace(/"/g,'""')+'"';}).join(','));});
    var b=new Blob([L.join('\n')],{type:'text/csv;charset=utf-8'});var a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='listagem.csv';a.click();}
  render();}
document.addEventListener('DOMContentLoaded',function(){var ts=document.querySelectorAll('table.smart');for(var k=0;k<ts.length;k++)init(ts[k]);});
})();
