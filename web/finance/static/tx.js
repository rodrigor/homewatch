/* tabela de transações: edição inline, sort, novo lançamento e split.
   Páginas definem window.ACOLOR (cores por conta) e window.TXACC (conta da aba) inline. */
function sv(id,field,el){var b='field='+field+'&value='+encodeURIComponent(el.value);
  fetch('/api/tx/'+id,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:b})
  .then(function(r){return r.json();}).then(function(j){el.classList.remove('err','saved');el.classList.add(j.ok?'saved':'err');
    if(j.ok&&field=='status'){var tr=el.closest('tr');tr.className='drow st-'+el.value;el.title=el.value;}
    setTimeout(function(){el.classList.remove('saved');},700);}).catch(function(){el.classList.add('err');});}
function sacc(id,el){sv(id,'account_id',el);el.style.setProperty('--ac',(window.ACOLOR&&ACOLOR[el.value])||'transparent');}
function sx(id,b){var on=b.classList.toggle('on');fetch('/api/tx/'+id,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'field=excepcional&value='+(on?1:0)});}
function dl(id){if(!confirm('Excluir esta transação?'))return;fetch('/api/tx/'+id+'/delete',{method:'POST'}).then(function(){location.reload();});}
function edt(b){var tr=b.closest('tr');var was=tr.classList.contains('editing');
  var es=document.querySelectorAll('tr.editing');for(var i=0;i<es.length;i++)es[i].classList.remove('editing');
  if(was)return;  // estava editando -> ✎ bloqueia de novo
  tr.classList.add('editing');var x=tr.querySelector('[data-k=desc] input');if(x){x.focus();if(x.select)x.select();}}
function addtx(){var g=function(i){var e=document.getElementById(i);return e?e.value:'';};if(!g('n_val')){alert('Informe o valor (use - para gasto, ex: -45,90).');return;}
  var b=new URLSearchParams({date:g('n_date'),description:g('n_desc'),favorecido:g('n_fav'),category:g('n_cat'),account_id:(g('n_acc')||window.TXACC||''),status:g('n_status'),valor:g('n_val')}).toString();
  fetch('/api/tx/new',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:b}).then(function(r){return r.json();}).then(function(j){if(j.ok)location.reload();else alert(j.err||'erro ao salvar');});}
var _td={};
function txsort(th,key){var t=th.closest('table');var rows=Array.prototype.slice.call(t.querySelectorAll('tr.drow'));
  if(!rows.length)return;
  _td[key]=!_td[key];var dir=_td[key]?1:-1;
  function val(r){if(key=='data')return r.querySelector('[data-k=data] input').value;
    if(key=='desc')return r.querySelector('[data-k=desc] input').value.toLowerCase();
    if(key=='fav')return r.querySelector('[data-k=fav] input').value.toLowerCase();
    if(key=='cat')return (r.querySelector('[data-k=cat] select').value||'~~~').toLowerCase();
    if(key=='conta'){var s=r.querySelector('[data-k=conta] select');if(!s)return '';return (s.options[s.selectedIndex].text||'~~~').toLowerCase();}
    if(key=='status')return r.querySelector('[data-k=status] select').value;
    if(key=='valor'){var v=r.querySelector('[data-k=valor] input').value;return parseFloat(v.split('.').join('').replace(',','.'))||0;}
    return '';}
  rows.sort(function(a,b){var va=val(a),vb=val(b);return va<vb?-dir:va>vb?dir:0;});
  var total=t.querySelector('tr.totrow');var tb=rows[0].parentNode;rows.forEach(function(r){tb.insertBefore(r,total);});
  var hs=t.querySelectorAll('.sc');for(var i=0;i<hs.length;i++)hs[i].textContent='';th.querySelector('.sc').textContent=dir>0?'▲':'▼';}
// ----- lançamento composto (split) -----
var SPLITID=null,SPLITTOT=0;
function _spc(s){if(!s)return 0;s=String(s);var neg=s.indexOf('-')>=0;var n=s.replace(/[^0-9]/g,'');var c=parseInt(n||'0',10)||0;return neg?-c:c;}
function _spfmt(c){return (c<0?'-':'')+(Math.abs(c)/100).toFixed(2).replace('.',',');}
function addSplitLine(cents){var d=document.createElement('div');d.className='splitrow';
  d.innerHTML='<select class=sp_cat>'+document.getElementById('splitopts').innerHTML+'</select>'
    +'<input class=sp_val placeholder="-0,00" oninput="splitCalc()">'
    +'<button class=spdel onclick="this.parentNode.remove();splitCalc()" title=remover>✕</button>';
  document.getElementById('splitrows').appendChild(d);
  if(cents){d.querySelector('.sp_val').value=_spfmt(cents);}splitCalc();}
function splitOpen(id,valstr){SPLITID=id;SPLITTOT=_spc(valstr);
  document.getElementById('splitrows').innerHTML='';addSplitLine(SPLITTOT);addSplitLine(0);
  document.getElementById('splitm').classList.add('on');splitCalc();
  var f=document.querySelector('#splitrows .sp_cat');if(f)f.focus();}
function splitCalc(){var vs=document.querySelectorAll('#splitrows .sp_val');var sum=0;for(var i=0;i<vs.length;i++)sum+=_spc(vs[i].value);
  var rem=SPLITTOT-sum;document.getElementById('splittot').textContent=_spfmt(SPLITTOT);
  var re=document.getElementById('splitrem');re.textContent=_spfmt(rem);re.style.color=rem===0?'var(--grn)':'var(--red)';
  document.getElementById('splitsave').disabled=(rem!==0);}
function splitSave(){var cs=document.querySelectorAll('#splitrows .sp_cat');var vs=document.querySelectorAll('#splitrows .sp_val');
  var parts=[];for(var i=0;i<vs.length;i++){if(_spc(vs[i].value)===0)continue;parts.push({category:cs[i].value,valor:vs[i].value});}
  if(parts.length<2){alert('Informe ao menos 2 partes com valor.');return;}
  fetch('/api/tx/'+SPLITID+'/split',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parts:parts})})
    .then(function(r){return r.json();}).then(function(j){if(j.ok)location.reload();else alert(j.err||'erro ao dividir');})
    .catch(function(){alert('erro de rede');});}
