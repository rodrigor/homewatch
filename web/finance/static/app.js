/* Finanças PIrrai — tema + CSRF */

// tema claro/escuro (o atributo inicial é setado inline no <head> antes do paint)
function toggleTheme(){var h=document.documentElement;var cur=h.getAttribute('data-theme')==='light'?'dark':'light';
  h.setAttribute('data-theme',cur);try{localStorage.setItem('fin-theme',cur);}catch(e){}
  var b=document.getElementById('themebtn');if(b)b.textContent=cur==='light'?'☀️':'🌙';}
document.addEventListener('DOMContentLoaded',function(){var b=document.getElementById('themebtn');
  if(b)b.textContent=document.documentElement.getAttribute('data-theme')==='light'?'☀️':'🌙';});

// CSRF: header em todo fetch POST + input escondido em todo form POST
(function(){
  var m=document.querySelector('meta[name=csrf]');window.CSRF=m?m.content:'';
  var of=window.fetch;
  window.fetch=function(u,o){o=o||{};
    if(((o.method||'GET')+'').toUpperCase()==='POST'){
      if(o.headers instanceof Headers){o.headers.set('X-CSRF',window.CSRF);}
      else{o.headers=o.headers||{};o.headers['X-CSRF']=window.CSRF;}}
    return of.call(window,u,o);};
  document.addEventListener('DOMContentLoaded',function(){
    var fs=document.querySelectorAll('form');
    for(var i=0;i<fs.length;i++){
      if((fs[i].method||'').toLowerCase()==='post'&&!fs[i].querySelector('input[name=_csrf]')){
        var inp=document.createElement('input');inp.type='hidden';inp.name='_csrf';inp.value=window.CSRF;
        fs[i].appendChild(inp);}}
  });
})();
