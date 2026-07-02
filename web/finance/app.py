#!/usr/bin/env python3
"""Finanças PIrrai — web app (F1 base): login, dashboard, listagem e lançamento manual.
Bind em 127.0.0.1:8090 (dados financeiros NÃO ficam expostos na LAN; acesso via VPN/SSH-tunnel)."""
import os, sys, json, sqlite3, subprocess, secrets, datetime, functools, uuid
from flask import (Flask, request, session, redirect, url_for,
                   render_template_string, flash, abort)
from werkzeug.security import check_password_hash

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../homewatch
sys.path.insert(0, ROOT)
import ofx_parser, finance_rules
DB = os.path.join(ROOT, "finance.db")
USERS = os.path.join(ROOT, "finance_users.json")
FINANCE_SH = os.path.join(ROOT, "finance.sh")
SECRET = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret")

app = Flask(__name__)
if not os.path.exists(SECRET):
    with open(SECRET, "w") as fh: fh.write(secrets.token_hex(32))
    os.chmod(SECRET, 0o600)
app.secret_key = open(SECRET).read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=7))

# ---------- helpers ----------
def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def users():
    try:
        with open(USERS) as fh: return json.load(fh)
    except Exception: return {}

def brl(cents):
    s = f"{abs(cents)/100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if cents < 0 else "") + "R$ " + s

def reais_plain(cents):  # "-67,90" para inputs editáveis
    return f"{cents/100:.2f}".replace(".", ",")

CUR_SYM = {"BRL": "R$", "USD": "US$", "EUR": "€", "GBP": "£", "ARS": "AR$", "UYU": "$U"}
def cursym(cur):
    return CUR_SYM.get((cur or "BRL").upper(), (cur or "BRL"))
def money(cents, cur="BRL"):  # valor com símbolo da moeda da transação
    s = f"{abs(cents)/100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if cents < 0 else "") + cursym(cur) + " " + s
def tot_by_currency(rows):    # [(moeda, soma_centavos), ...] ordenado
    m = {}
    for r in rows:
        k = (r["currency"] or "BRL")
        m[k] = m.get(k, 0) + r["amount"]
    return sorted(m.items())
def val_label_for(rows):      # símbolo p/ cabeçalho: único quando 1 moeda, senão genérico
    if not rows: return "R$"
    curs = {(r["currency"] or "BRL") for r in rows}
    return cursym(next(iter(curs))) if len(curs) == 1 else "moeda"

def parse_cents(s):  # "-67,90" / "R$ 1.234,56" / "45.90" -> centavos (preserva sinal)
    s = (s or "").replace("R$", "").replace(" ", "").strip()
    neg = s.startswith("-"); s = s.lstrip("+-").replace(".", "").replace(",", ".")
    try: c = int(round(float(s) * 100))
    except Exception: return None
    return -c if neg else c

STATUSES = ["pendente", "confirmado", "conciliado", "importado", "agendado"]
STATUS_ICONS = {"pendente": "⏳", "confirmado": "✅", "conciliado": "🔗", "importado": "📥", "agendado": "📅"}
STATUS_GLYPH = {"pendente": "○", "confirmado": "✓", "conciliado": "⇄", "importado": "↓", "agendado": "◷"}  # não-emoji, monocromáticos
# ícones SVG de origem da transação (sem emoji)
_S = 'width=13 height=13 viewBox="0 0 13 13" fill=none stroke=currentColor stroke-width=1.4'
SRC_ICONS = {
    "email":    f'<svg {_S} title="e-mail"><rect x=".8" y="2" width="11.4" height="8.5" rx=".9"/><path d="M.8 2.5L6.5 7l5.7-4.5"/></svg>',
    "manual":   f'<svg {_S} title="manual"><path d="M8.5 1.5l3 3-6.5 6.5H2v-3l6.5-6.5z"/><path d="M7 3l3 3"/></svg>',
    "telegram": f'<svg {_S} title="Telegram"><path d="M1.5 6.5l9-5-2.5 9.5-3.5-3.5-1.5 1.5V7l-1.5-.5z"/><path d="M4.5 7.5L8 4"/></svg>',
    "ofx":      f'<svg {_S} title="OFX/extrato"><path d="M6.5 1v8M3.5 6l3 3 3-3"/><line x1="1" y1="12" x2="12" y2="12"/></svg>',
    "split":    f'<svg {_S} title="divisão"><path d="M1 3.5h5l2-2.5M1 9.5h5l2 2.5"/><path d="M6 6.5h6"/><circle cx="12" cy="6.5" r=".8" fill=currentColor/></svg>',
}
SRC_ICONS_LABELS = {"email": "e-mail", "manual": "manual", "telegram": "Telegram", "ofx": "OFX/extrato", "split": "divisão"}
# movimentações (categorias is_transfer=1) não contam como gasto/receita
NOTRANSFER = "COALESCE(category,'') NOT IN (SELECT name FROM categories WHERE is_transfer=1)"

def login_required(f):
    @functools.wraps(f)
    def w(*a, **k):
        if "user" not in session: return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w

app.jinja_env.filters["brl"] = brl
app.jinja_env.filters["reais_plain"] = reais_plain
app.jinja_env.filters["money"] = money
app.jinja_env.globals["cursym"] = cursym

TITULARES = ["Ayla", "Rodrigo", "Casa"]  # dono da conta (atribui as despesas a uma pessoa)

def _ensure_schema():
    """migração idempotente: garante a coluna accounts.titular e auto-detecta pelo nome."""
    try:
        c = db()
        cols = [r[1] for r in c.execute("PRAGMA table_info(accounts)")]
        if "titular" not in cols:
            c.execute("ALTER TABLE accounts ADD COLUMN titular TEXT")
            c.execute("UPDATE accounts SET titular='Ayla'    WHERE titular IS NULL AND lower(name) LIKE '%ayla%'")
            c.execute("UPDATE accounts SET titular='Rodrigo' WHERE titular IS NULL AND lower(name) LIKE '%rodrigo%'")
            c.commit()
        tcols = [r[1] for r in c.execute("PRAGMA table_info(transactions)")]
        if "split_group" not in tcols:           # lançamento composto: liga as partes de uma divisão
            c.execute("ALTER TABLE transactions ADD COLUMN split_group INTEGER")
            c.commit()
        rcols = [r[1] for r in c.execute("PRAGMA table_info(rules)")]   # regras por faixa de dias/conta/favorecido
        for cn, ct in (("dom_min", "INTEGER"), ("dom_max", "INTEGER"), ("account_id", "INTEGER"), ("set_fav", "TEXT")):
            if cn not in rcols: c.execute(f"ALTER TABLE rules ADD COLUMN {cn} {ct}")
        # IOF/spread: taxa-padrão por conta (contas globais) + valor real por transação
        acols = [r[1] for r in c.execute("PRAGMA table_info(accounts)")]
        for cn in ("iof_rate", "spread_rate"):
            if cn not in acols: c.execute(f"ALTER TABLE accounts ADD COLUMN {cn} REAL DEFAULT 0")
        if "entra_orcamento" not in acols:   # conta entra no orçamento (receitas/despesas/teto)?
            c.execute("ALTER TABLE accounts ADD COLUMN entra_orcamento INTEGER DEFAULT 1")
            # contas globais (não-BRL) e de investimento ficam fora por padrão
            c.execute("UPDATE accounts SET entra_orcamento=0 WHERE COALESCE(currency,'BRL')<>'BRL' OR lower(COALESCE(type,'')) LIKE '%invest%'")
        tcols2 = [r[1] for r in c.execute("PRAGMA table_info(transactions)")]
        for cn in ("iof_amount", "spread_amount"):       # centavos; breakdown da conversão (perna em BRL)
            if cn not in tcols2: c.execute(f"ALTER TABLE transactions ADD COLUMN {cn} INTEGER")
        if "transfer_group" not in tcols2:               # UUID compartilhado entre as duas pernas
            c.execute("ALTER TABLE transactions ADD COLUMN transfer_group TEXT")
        c.commit()
        c.close()
    except Exception:
        pass
_ensure_schema()

# ---------- templates ----------
BASE = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Finanças · PIrrai</title>
<script>(function(){try{var t=localStorage.getItem('fin-theme')||'dark';document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<style>
:root,html[data-theme=dark]{--bg:#0f1419;--card:#1a2230;--ink:#e6edf3;--mut:#8b98a9;--ln:#263041;--acc:#2f81f7;--red:#f85149;--grn:#3fb950;--inbg:#0d1117}
html[data-theme=light]{--bg:#f5f7fa;--card:#ffffff;--ink:#1a2230;--mut:#5b6776;--ln:#d8dee6;--acc:#1f6feb;--red:#d1242f;--grn:#1a7f37;--inbg:#eef1f5}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:var(--acc);text-decoration:none}.wrap{max-width:none;margin:0 auto;padding:18px 26px}
header{display:flex;align-items:center;gap:16px;border-bottom:1px solid var(--ln);padding:14px 18px;background:var(--card)}
header b{font-size:18px}header nav{display:flex;gap:14px;margin-left:auto;align-items:center}
.themebtn{background:transparent;border:0;padding:0 2px;font-size:16px;line-height:1;cursor:pointer;color:var(--ink)}
.card{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:12px;margin-bottom:18px}
.kpi .v{font-size:19px;font-weight:700;white-space:nowrap;letter-spacing:-.3px}.kpi .l{color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--ln)}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.neg{color:var(--red)}.pos{color:var(--grn)}.tag{font-size:12px;color:var(--mut)}
input,select,button{font:inherit;padding:9px 11px;border-radius:9px;border:1px solid var(--ln);background:var(--inbg);color:var(--ink)}
.fon{border-color:var(--acc)!important;box-shadow:0 0 0 1px var(--acc);font-weight:600}
button,.btn{background:var(--acc);border:0;color:#fff;cursor:pointer;font-weight:600;padding:9px 16px}
.flash{background:#1f6feb22;border:1px solid var(--acc);padding:10px 14px;border-radius:9px;margin-bottom:14px}
form.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}label{display:block;font-size:13px;color:var(--mut);margin-bottom:4px}
.full{grid-column:1/-1}.muted{color:var(--mut)}
.modal{display:none;position:fixed;inset:0;background:#000a;z-index:50;align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto}
.modal.on{display:flex}
.modalbox{background:var(--card);border:1px solid var(--ln);border-radius:14px;max-width:560px;width:100%;box-shadow:0 20px 60px #000a}
.modalhd{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--ln)}
.modalhd b{flex:1}.mclose{background:transparent;border:0;color:var(--mut);font-size:18px;cursor:pointer;padding:0 4px}.mclose:hover{color:var(--red)}
.modalbody{padding:16px 18px 18px}
</style></head><body>
{% if session.user %}<header><b>💰 Finanças</b>
<nav><a href="https://pirrai.tail414b9b.ts.net/" title="serviços do PIrrai">🏠</a><a href="{{url_for('financas')}}">Resumo</a><a href="{{url_for('transacoes')}}">Transações</a><a href="{{url_for('favorecidos')}}">Favorecidos</a>
<a href="{{url_for('grupos')}}">Grupos</a><a href="{{url_for('contas')}}">Contas</a><a href="{{url_for('transferencia')}}">↔ Transferência</a><a href="{{url_for('investimentos')}}">📈 Invest.</a><a href="{{url_for('regras')}}">Regras</a><a href="{{url_for('limites')}}">Limites</a><a href="{{url_for('conciliacao')}}">Conciliar</a><a href="{{url_for('senha')}}">Senha</a>
<button id=themebtn class=themebtn onclick="toggleTheme()" title="tema claro/escuro">🌙</button>
<span class=muted>{{session.user}}</span><a href="{{url_for('logout')}}">sair</a></nav></header>{% endif %}
<script>
function toggleTheme(){var h=document.documentElement;var cur=h.getAttribute('data-theme')==='light'?'dark':'light';
  h.setAttribute('data-theme',cur);try{localStorage.setItem('fin-theme',cur);}catch(e){}
  var b=document.getElementById('themebtn');if(b)b.textContent=cur==='light'?'☀️':'🌙';}
document.addEventListener('DOMContentLoaded',function(){var b=document.getElementById('themebtn');
  if(b)b.textContent=document.documentElement.getAttribute('data-theme')==='light'?'☀️':'🌙';});
</script>
<div class=wrap>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m|join(' · ')}}</div>{% endif %}{% endwith %}
{% block body %}{% endblock %}</div></body></html>"""

# ---------- smart-table: componente reutilizável (sort + filtros + agrupar/subtotais + CSV) ----------
SMART = r"""<style>
.smartbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px}
.smartbar input,.smartbar select{font-size:13px;padding:7px 9px;border-radius:8px;border:1px solid var(--ln);background:var(--inbg);color:var(--ink)}
.smartbar .btn{padding:7px 12px}
table.smart th .sc{color:var(--acc);font-size:11px;margin-left:2px}
table.smart tr.grouphdr td{background:var(--inbg)}table.smart tr.smarttot td{border-top:2px solid var(--ln)}
</style>
<script>
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
</script>"""
BASE = BASE.replace("</body>", SMART + "</body>")

# ---------- componente de listagem de TRANSAÇÕES (colunas padrão + edição inline + ✎/❗/✕) ----------
TX_HEAD = """<tr>
  <th class=dt onclick="txsort(this,'data')" style=cursor:pointer>Data <span class=sc></span></th>
  <th onclick="txsort(this,'desc')" style=cursor:pointer>Descrição <span class=sc></span></th>
  <th onclick="txsort(this,'fav')" style=cursor:pointer>Favorecido <span class=sc></span></th>
  <th onclick="txsort(this,'cat')" style=cursor:pointer>Categoria <span class=sc></span></th>
  {% if show_conta|default(true) %}<th onclick="txsort(this,'conta')" style=cursor:pointer>Conta <span class=sc></span></th>{% endif %}
  <th class=st onclick="txsort(this,'status')" style="cursor:pointer;text-align:center">Status <span class=sc></span></th>
  <th class=vl onclick="txsort(this,'valor')" style="cursor:pointer;text-align:right">Valor ({{ val_label|default('R$') }}) <span class=sc></span></th>
  <th style=text-align:right></th></tr>"""
TX_ROWS = """{% for r in rows %}<tr class="drow st-{{r['status']}}">
  <td data-k=data><input type=datetime-local class=dt value="{{r['date']}}T{{(r['time'] or '00:00')[:5]}}" onchange="sv({{r['id']}},'datetime',this)"></td>
  <td data-k=desc><input value="{{r['description'] or ''}}" onchange="sv({{r['id']}},'description',this)"></td>
  <td data-k=fav><input value="{{r['favorecido'] or ''}}" onchange="sv({{r['id']}},'favorecido',this)"></td>
  <td data-k=cat><select onchange="sv({{r['id']}},'category',this)"><option value="">—</option>{% for g,names in cat_groups.items() %}<optgroup label="{{g}}">{% for nm in names %}<option {{'selected' if r['category']==nm}}>{{nm}}</option>{% endfor %}</optgroup>{% endfor %}</select></td>
  {% if show_conta|default(true) %}<td data-k=conta><select class=acct style="--ac:{{ acolor.get(r['account_id'],'transparent') }}" onchange="sacc({{r['id']}},this)"><option value="">—</option>{% for a in accs %}<option value="{{a['id']}}" {{'selected' if r['account_id']==a['id']}}>{{a['name']}}</option>{% endfor %}</select></td>{% endif %}
  <td data-k=status><span class=srcico title="{{r['source']}}">{{ src_icons.get(r['source'] or 'manual', src_icons['manual']) | safe }}</span><select class=stsel title="{{r['status']}}" onchange="sv({{r['id']}},'status',this)">{% for s in statuses %}<option value="{{s}}" {{'selected' if r['status']==s}}>{{glyph[s]}}</option>{% endfor %}</select></td>
  <td data-k=valor>{% if r['currency'] and r['currency']!='BRL' %}<span title="{{r['currency']}}" style="font-size:11px;color:var(--mut);margin-right:4px;vertical-align:middle">{{cursym(r['currency'])}}</span>{% endif %}<input class="val {{'pos' if r['amount']>0 else 'neg'}}" value="{{r['amount']|reais_plain}}" onchange="sv({{r['id']}},'amount',this)" style=text-align:right></td>
  <td class=txact><button class=edt onclick="edt(this)" title="editar / bloquear">✎</button><button class="excb {{'on' if r['excepcional']}}" onclick="sx({{r['id']}},this)" title="excepcional (fora do normal)">❗</button>{% if r['split_group'] %}<span class=spmark title="parte de lançamento dividido (grupo {{r['split_group']}})">⊂</span>{% else %}<button class=splb onclick="splitOpen({{r['id']}},'{{r['amount']|reais_plain}}')" title="dividir lançamento">✂</button>{% endif %}<button class=del onclick="dl({{r['id']}})" title=excluir>✕</button></td>
</tr>{% endfor %}"""
TX_TOTAL = """{% if rows %}{% if totais is defined and totais %}{% for cur,val in totais %}<tr class=totrow><td colspan="{{ 6 if show_conta|default(true) else 5 }}" style=text-align:right class=muted>Total{% if totais|length>1 %} {{cur}}{% endif %}</td><td style=text-align:right class="{{'pos' if val>0 else 'neg'}}"><b>{{val|money(cur)}}</b></td><td></td></tr>{% endfor %}{% else %}<tr class=totrow><td colspan="{{ 6 if show_conta|default(true) else 5 }}" style=text-align:right class=muted>Total</td><td style=text-align:right class="{{'pos' if tot>0 else 'neg'}}"><b>{{tot|brl}}</b></td><td></td></tr>{% endif %}{% endif %}"""
TX_JS = """<script>window.ACOLOR={{acolor|tojson}};</script>
<style>
.txtbl{font-size:13px}.txtbl td,.txtbl th{padding:6px 6px}.txtbl .dt{max-width:195px}.txtbl .st{max-width:70px}
.txtbl input,.txtbl select{background:transparent;border:1px solid transparent;border-radius:6px;color:var(--ink);padding:5px 6px;width:100%;font-size:13px}
.txtbl input:hover,.txtbl select:hover{border-color:var(--ln)}.txtbl input:focus,.txtbl select:focus{border-color:var(--acc);background:var(--inbg);outline:none}
.txtbl .val.neg{color:var(--red)}.txtbl .val.pos{color:var(--grn)}.saved{background:#3fb95033!important}.err{border-color:var(--red)!important}
.stsel{max-width:56px;text-align:center;font-size:15px;font-weight:700}
tr.st-pendente .stsel{color:#d29922}tr.st-confirmado .stsel{color:var(--grn)}tr.st-conciliado .stsel{color:#2f81f7}tr.st-importado .stsel{color:var(--red)}tr.st-agendado .stsel{color:#a371f7}
.acct{border-left:4px solid var(--ac,transparent)!important;padding-left:8px!important}
.srcico{display:inline-flex;align-items:center;margin-right:4px;color:var(--mut);vertical-align:middle;opacity:.7}
.srcico:hover{opacity:1}
.slegend{font-size:12px;color:var(--mut);margin-bottom:8px;display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.txact{white-space:nowrap;text-align:right}.txact button{background:transparent;border:0;cursor:pointer;font-size:14px;padding:3px 5px;color:var(--mut)}
.txact .edt:hover{color:var(--acc)}.txact .del:hover{color:var(--red)}.txact .excb.on{color:#d29922}.txact .excb:hover{color:#d29922}.txact .addb{background:var(--grn);color:#fff;border-radius:6px;padding:3px 11px;font-weight:700;font-size:15px}
tr.editing td{background:#2f81f714}tr.newrow{background:#2f81f714}tr.st-pendente{background:#f0883e0e}tr.st-conciliado{background:#3fb9500a}tr.st-importado{background:#f8514910}
.txtbl tr.drow:not(.editing) input,.txtbl tr.drow:not(.editing) select{pointer-events:none}
.txtbl tr.drow:not(.editing) [data-k=cat] select{-webkit-appearance:none;-moz-appearance:none;appearance:none;text-indent:0}
.txtbl tr.editing .edt{color:var(--acc)}
</style>
<script>
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
</script>
<style>
.spmark{color:var(--mut);font-size:13px;padding:3px 5px;cursor:default}
.txact .splb:hover{color:var(--acc)}
#splitrows .splitrow{display:flex;gap:6px;margin-bottom:6px;align-items:center}
#splitrows .sp_cat{flex:1;background:var(--inbg);border:1px solid var(--ln);border-radius:6px;color:var(--ink);padding:6px;font-size:13px}
#splitrows .sp_val{width:120px;text-align:right;background:var(--inbg);border:1px solid var(--ln);border-radius:6px;color:var(--ink);padding:6px;font-size:13px}
#splitrows .spdel{background:transparent;border:0;color:var(--mut);cursor:pointer;font-size:14px}#splitrows .spdel:hover{color:var(--red)}
.spadd{background:var(--ln);color:var(--ink);border:0;border-radius:7px;padding:7px 12px;cursor:pointer;font-size:13px}
.spsave{margin-left:auto;background:var(--grn);color:#fff;border:0;border-radius:7px;padding:7px 14px;cursor:pointer;font-weight:700;font-size:13px}
.spsave:disabled{opacity:.45;cursor:not-allowed}
</style>"""

# monta a página injetando o corpo no template base (sem depender de extends por arquivo)
def render(inner, **ctx):
    full = BASE.replace("{% block body %}{% endblock %}", inner)
    return render_template_string(full, **ctx)

# ---------- auth ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("user", "").strip(); p = request.form.get("pw", "")
        rec = users().get(u)
        if rec and check_password_hash(rec["hash"], p):
            session["user"] = u; session["role"] = rec.get("role", "editor")
            return redirect(request.args.get("next") or url_for("financas"))
        flash("Usuário ou senha inválidos.")
    inner = """<div class=card style="max-width:360px;margin:8vh auto">
    <h2 style="margin-top:0">💰 Finanças · PIrrai</h2>
    <form method=post><label>Usuário</label><input name=user autofocus style=width:100%>
    <label style=margin-top:10px>Senha</label><input name=pw type=password style=width:100%>
    <button style="margin-top:16px;width:100%">Entrar</button></form></div>"""
    return render(inner)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

# ---------- dashboard financeiro ----------
@app.route("/financas")
@login_required
def financas():
    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    c = db()
    desp = c.execute(f"SELECT COALESCE(-SUM(amount),0) FROM transactions WHERE amount<0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=0", (mes,)).fetchone()[0]
    exc  = c.execute(f"SELECT COALESCE(-SUM(amount),0) FROM transactions WHERE amount<0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=1", (mes,)).fetchone()[0]
    rec  = c.execute(f"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE amount>0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=0", (mes,)).fetchone()[0]
    n    = c.execute("SELECT COUNT(*) FROM transactions WHERE substr(date,1,7)=?", (mes,)).fetchone()[0]
    pend = c.execute("SELECT COUNT(*) FROM transactions WHERE status='pendente'").fetchone()[0]
    grupos = c.execute("""SELECT COALESCE(c.grupo,'(sem grupo)') g, -SUM(t.amount) v
                          FROM transactions t LEFT JOIN categories c ON c.name=t.category
                          WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(c.is_transfer,0)=0 AND COALESCE(t.excepcional,0)=0
                          GROUP BY c.grupo ORDER BY v DESC""", (mes,)).fetchall()
    cats = c.execute(f"""SELECT COALESCE(category,'—') cat, -SUM(amount) v FROM transactions
                        WHERE amount<0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=0 GROUP BY category ORDER BY v DESC""", (mes,)).fetchall()
    orc = c.execute("""SELECT b.category cat, b.limit_amount lim,
        COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=b.category AND amount<0 AND substr(date,1,7)=?),0) spent
        FROM budgets b WHERE b.month='*' AND b.limit_amount>0
        ORDER BY (spent*1.0/b.limit_amount) DESC""", (mes,)).fetchall()
    meses_raw = c.execute(f"""SELECT substr(date,1,7) m,
        -SUM(CASE WHEN amount<0 AND COALESCE(excepcional,0)=0 THEN amount ELSE 0 END) rec,
        -SUM(CASE WHEN amount<0 AND COALESCE(excepcional,0)=1 THEN amount ELSE 0 END) exc,
         SUM(CASE WHEN amount>0 AND COALESCE(excepcional,0)=0 THEN amount ELSE 0 END) receita
        FROM transactions WHERE {NOTRANSFER}
        GROUP BY m ORDER BY m DESC LIMIT 12""").fetchall()
    # --- Estrutura de gasto por nível ---
    nivel_rows = c.execute("""
        SELECT COALESCE(cat.nivel, t.email_hint_nivel, 0) niv, -SUM(t.amount) total
        FROM transactions t LEFT JOIN categories cat ON cat.name=t.category
        WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(cat.is_transfer,0)=0 AND COALESCE(t.excepcional,0)=0
        GROUP BY COALESCE(cat.nivel, t.email_hint_nivel, 0) ORDER BY niv""", (mes,)).fetchall()
    nivel_map = {r["niv"]: r["total"] for r in nivel_rows}
    n1 = nivel_map.get(1, 0); n2 = nivel_map.get(2, 0); n3 = nivel_map.get(3, 0); n0 = nivel_map.get(0, 0)
    niv_cat_rows = c.execute("""
        SELECT COALESCE(cat.nivel, t.email_hint_nivel, 0) niv, COALESCE(NULLIF(t.category,''),'(sem categoria)') cat, -SUM(t.amount) v
        FROM transactions t LEFT JOIN categories cat ON cat.name=t.category
        WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(cat.is_transfer,0)=0 AND COALESCE(t.excepcional,0)=0
        GROUP BY COALESCE(cat.nivel, t.email_hint_nivel, 0), t.category
        ORDER BY COALESCE(cat.nivel, t.email_hint_nivel, 0), v DESC""", (mes,)).fetchall()
    # --- distribuição N1/N2/N3 por pessoa (titular da conta); recorrentes + excepcionais ---
    pessoa_rows = c.execute("""
        SELECT COALESCE(a.titular,'(sem titular)') pessoa, COALESCE(cat.nivel, t.email_hint_nivel, 0) niv, -SUM(t.amount) v
        FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        LEFT JOIN categories cat ON cat.name=t.category
        WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(cat.is_transfer,0)=0
        GROUP BY a.titular, COALESCE(cat.nivel, t.email_hint_nivel, 0)""", (mes,)).fetchall()
    obrigatorio = n1 + n2
    cfg_sal = c.execute("SELECT value FROM config WHERE key='salario_base'").fetchone()
    salario_base = int(cfg_sal[0]) if cfg_sal else 0
    # --- Seção orçamento: teto dos essenciais (N1+N2 vs salários) e resultado, contas no orçamento, 6 meses ---
    BUD = "t.account_id IN (SELECT id FROM accounts WHERE COALESCE(entra_orcamento,1)=1)"
    NIVX = "COALESCE((SELECT nivel FROM categories WHERE name=t.category), t.email_hint_nivel, 0)"
    TRX = "COALESCE(t.category,'') IN (SELECT name FROM categories WHERE is_transfer=1)"
    def _msum(mo, cond):
        return c.execute(f"SELECT COALESCE(SUM(amount),0) FROM transactions t WHERE substr(t.date,1,7)=? AND {BUD} AND {cond}", (mo,)).fetchone()[0] or 0
    _y, _m = int(mes[:4]), int(mes[5:7]); _win = []
    for _k in range(5, -1, -1):
        _mm, _yy = _m - _k, _y
        while _mm <= 0: _mm += 12; _yy -= 1
        _win.append(f"{_yy:04d}-{_mm:02d}")
    orcserie = []
    for mo in _win:
        orcserie.append({"ym": mo,
            "n1": -_msum(mo, f"amount<0 AND NOT ({TRX}) AND {NIVX}=1"),
            "n2": -_msum(mo, f"amount<0 AND NOT ({TRX}) AND {NIVX}=2"),
            "n3": -_msum(mo, f"amount<0 AND NOT ({TRX}) AND {NIVX}=3"),
            "n0": -_msum(mo, f"amount<0 AND NOT ({TRX}) AND {NIVX}=0"),
            "sal": _msum(mo, "category='Salário'"),
            "rec": _msum(mo, f"amount>0 AND NOT ({TRX})")})
    acolor = {a["id"]: (a["color"] or "#888") for a in c.execute("SELECT id,color FROM accounts").fetchall()}
    c.close()
    NIV_LABEL = {1: "N1 · Comprometido", 2: "N2 · Necessário variável", 3: "N3 · Discricionário", 0: "N0 · Sem nível"}
    NIV_COLOR = {1: "#2f81f7", 2: "#3fb950", 3: "#ef6c00", 0: "#6e7681"}
    niv_detail = []
    for lv in (1, 2, 3, 0):
        items = [(r["cat"], r["v"]) for r in niv_cat_rows if r["niv"] == lv]
        if items:
            niv_detail.append({"label": NIV_LABEL[lv], "color": NIV_COLOR[lv],
                               "total": sum(v for _, v in items), "items": items})
    # agrega despesas por pessoa × nível e ordena (Ayla, Rodrigo, Casa, demais)
    pmap = {}
    for r in pessoa_rows:
        d = pmap.setdefault(r["pessoa"], {0: 0, 1: 0, 2: 0, 3: 0})
        d[r["niv"]] = d.get(r["niv"], 0) + r["v"]
    _ordem = ["Ayla", "Rodrigo", "Casa"]
    _pnomes = [p for p in _ordem if p in pmap] + sorted(p for p in pmap if p not in _ordem)
    pessoas = []
    for p in _pnomes:
        d = pmap[p]; base = d[1] + d[2] + d[3]
        if base <= 0: continue   # seção é sobre N1/N2/N3
        pessoas.append({"nome": p, "n1": d[1], "n2": d[2], "n3": d[3], "n0": d[0], "base": base})
    MESN = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
    mm = list(reversed(meses_raw))
    maxm = max([max(r["rec"] + r["exc"], r["receita"]) for r in mm], default=1) or 1
    meses = []
    for r in mm:
        meses.append({"label": f'{MESN[int(r["m"][5:7]) - 1]}/{r["m"][2:4]}', "atual": r["m"] == mes,
                      "rec": r["rec"], "exc": r["exc"], "receita": r["receita"],
                      "rec_px": round(r["rec"] / maxm * 150), "exc_px": round(r["exc"] / maxm * 150),
                      "receita_px": round(r["receita"] / maxm * 150)})
    maxg = max([r["v"] for r in grupos], default=1) or 1
    totg = sum(r["v"] for r in grupos) or 1
    inner = """<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
    <h2 style="margin:0;flex:1">Resumo</h2>
    <form><input type=month name=mes value="{{mes}}" onchange=this.form.submit()></form></div>
    <div class=grid>
    <div class="card kpi"><div class=l>Despesas (recorrentes)</div><div class="v neg">{{desp|brl}}</div></div>
    {% if exc %}<div class="card kpi"><div class=l>Excepcionais</div><div class="v" style=color:#d29922>{{exc|brl}}</div><div class=tag>fora do normal</div></div>{% endif %}
    <div class="card kpi"><div class=l>Receitas</div><div class="v pos">{{rec|brl}}</div></div>
    <div class="card kpi"><div class=l>Saldo</div><div class="v">{{(rec-desp)|brl}}</div></div>
    <div class="card kpi"><div class=l>Transações</div><div class=v>{{n}}</div><div class=tag>{{pend}} pendente(s)</div></div></div>
    {% if meses %}<div class=card><h3 style=margin-top:0>Despesas e receitas mês a mês</h3>
    <div class=mchart>
      {% for m in meses %}<div class="mcol{{' on' if m.atual}}">
        <div class=mbars>
          <div class=mbar title="Despesas: {{(m.rec+m.exc)|brl}}">
            {% if m.exc_px %}<div style="height:{{m.exc_px}}px;background:#d29922" title="excepcional: {{m.exc|brl}}"></div>{% endif %}
            <div style="height:{{m.rec_px}}px;background:var(--red)" title="recorrente: {{m.rec|brl}}"></div>
          </div>
          <div class=mbar title="Receitas: {{m.receita|brl}}">
            <div style="height:{{m.receita_px}}px;background:var(--grn)"></div>
          </div>
        </div>
        <div class=mlbl>{{m.label}}</div>
      </div>{% endfor %}
    </div>
    <div class=tag style=margin-top:8px><span style="color:var(--red)">■</span> despesa &nbsp; <span style="color:#d29922">■</span> excepcional &nbsp; <span style="color:var(--grn)">■</span> receita</div></div>{% endif %}
    <div class=card>
      <div style="display:flex;align-items:center;margin-bottom:4px"><h3 style="margin:0;flex:1">Teto dos essenciais e resultado</h3>
        <a class=tag href="{{url_for('contas')}}">contas no orçamento →</a></div>
      <p class=tag style="margin:0 0 14px">Só contas marcadas “entra no orçamento” (exclui Conta Global, investimentos). Regra da casa: N1+N2 ≤ salários.</p>
      <div style="font-size:13px;font-weight:600;margin:2px 0 8px">Teto dos essenciais — N1+N2 vs salários</div>
      <div class=orcleg><span><i style="background:#534AB7"></i>N1 comprometido</span><span><i style="background:#7F77DD"></i>N2 necessário</span><span><i style="width:16px;height:0;border-top:2px dashed #2ea043;border-radius:0;background:none"></i>salários (teto)</span></div>
      <div style="position:relative;width:100%;height:230px;margin-bottom:20px"><canvas id="orc_teto" role="img" aria-label="Barras empilhadas N1+N2 por mês com linha de salários (teto)."></canvas></div>
      <div style="font-size:13px;font-weight:600;margin:2px 0 8px">Resultado — despesas por nível vs receitas</div>
      <div class=orcleg><span><i style="background:#534AB7"></i>N1</span><span><i style="background:#7F77DD"></i>N2</span><span><i style="background:#AFA9EC"></i>N3</span><span><i style="background:#B4B2A9"></i>sem cat.</span><span><i style="width:16px;height:0;border-top:2px dashed #3fb950;border-radius:0;background:none"></i>receitas</span></div>
      <div style="position:relative;width:100%;height:240px"><canvas id="orc_res" role="img" aria-label="Barras empilhadas de despesas por nível por mês com linha de receitas."></canvas></div>
      <style>.orcleg{display:flex;flex-wrap:wrap;gap:7px 16px;font-size:12px;color:var(--mut);margin-bottom:6px;align-items:center}
      .orcleg i{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:middle;margin-right:5px}</style>
    </div>
    <script>window.ORCSERIE={{orcserie_json|safe}};</script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
    <script>
    (function(){
      var S=window.ORCSERIE; if(!S||!S.length) return;
      var MN=['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
      var L=S.map(function(d){return MN[parseInt(d.ym.slice(5,7),10)-1]+'/'+d.ym.slice(2,4);});
      var col=function(k){return S.map(function(d){return Math.round((d[k]||0)/100);});};
      var fmt=function(v){return 'R$ '+Math.round(v).toLocaleString('pt-BR');};
      function bar(l,k,c){return {type:'bar',label:l,data:col(k),backgroundColor:c,stack:'s',borderRadius:2};}
      function ln(l,k,c){return {type:'line',label:l,data:col(k),borderColor:c,borderDash:[6,4],borderWidth:2,pointStyle:'rectRot',pointRadius:4,pointBackgroundColor:c};}
      function mk(id,ds){new Chart(document.getElementById(id),{data:{labels:L,datasets:ds},
        options:{responsive:true,maintainAspectRatio:false,
          plugins:{legend:{display:false},tooltip:{callbacks:{label:function(x){return x.dataset.label+': '+fmt(x.raw);}}}},
          scales:{x:{stacked:true,grid:{display:false},ticks:{color:'#8b98a9',font:{size:12},autoSkip:false}},
            y:{stacked:true,grid:{color:'rgba(150,150,150,.12)'},ticks:{color:'#8b98a9',font:{size:12},callback:function(v){return 'R$ '+(v/1000)+'k';}}}}});}
      function run(){
        mk('orc_teto',[bar('N1','n1','#534AB7'),bar('N2','n2','#7F77DD'),ln('Salários','sal','#2ea043')]);
        mk('orc_res',[bar('N1','n1','#534AB7'),bar('N2','n2','#7F77DD'),bar('N3','n3','#AFA9EC'),bar('sem cat.','n0','#B4B2A9'),ln('Receitas','rec','#3fb950')]);
      }
      if(window.Chart)run(); else {var t=setInterval(function(){if(window.Chart){clearInterval(t);run();}},60);}
    })();
    </script>
    <div class=card><div style="display:flex;align-items:center;margin-bottom:10px"><h3 style="margin:0;flex:1">Estrutura de gasto</h3>
      <a class=tag href="{{url_for('grupos')}}">editar níveis →</a></div>
    {% set total_niv = n1+n2+n3+n0 or 1 %}
    {% set cores = {1:'#2f81f7', 2:'#3fb950', 3:'#ef6c00', 0:'#6e7681'} %}
    {% set labels = {1:'Comprometido', 2:'Necessário variável', 3:'Discricionário', 0:'Sem classificação'} %}
    {% for niv, val in [(1,n1),(2,n2),(3,n3)] if val > 0 %}
    <div class=gbar>
      <div class=gl><span class=catlink data-tipo=nivel data-val="{{niv}}" data-lbl="N{{niv}} {{labels[niv]}}" onclick="openTx(this)" title="ver transações">N{{niv}} {{labels[niv]}}</span></div>
      <div class=gt><div class=gf style="width:{{(val/total_niv*100)|round(1)}}%;background:{{cores[niv]}}"></div></div>
      <div class=gv>{{val|brl}} <span class=tag>{{(val/total_niv*100)|round(0)|int}}%</span></div>
    </div>{% endfor %}
    {% if n0 > 0 %}<div class=gbar>
      <div class=gl style="color:var(--mut)"><span class=catlink data-tipo=nivel data-val="0" data-lbl="Sem nível" onclick="openTx(this)" title="ver transações">Sem nível</span></div>
      <div class=gt><div class=gf style="width:{{(n0/total_niv*100)|round(1)}}%;background:#6e7681"></div></div>
      <div class=gv style="color:var(--mut)">{{n0|brl}} <span class=tag>{{(n0/total_niv*100)|round(0)|int}}%</span></div>
    </div>{% endif %}
    <hr style="border:none;border-top:1px solid var(--ln);margin:10px 0">
    <div style="display:flex;gap:24px;flex-wrap:wrap;font-size:14px">
      <div><span class=tag>Obrigatório (N1+N2)</span><br><b style="color:#2f81f7">{{obrigatorio|brl}}</b></div>
      <div><span class=tag>Discricionário (N3)</span><br><b style="color:#ef6c00">{{n3|brl}}</b></div>
      {% if salario_base > 0 %}
      <div><span class=tag>Salário base</span><br><b>{{salario_base|brl}}</b></div>
      <div><span class=tag>Obrig. vs salário</span><br>
        {% set pct = (obrigatorio*100//salario_base) %}
        <b style="color:{{'var(--red)' if pct>100 else ('#d29922' if pct>80 else 'var(--grn)')}}">{{pct}}%</b>
        <span class=tag>{{'⚠️ estourou' if pct>100 else ('⚠️ apertado' if pct>80 else '✅ ok')}}</span>
      </div>{% else %}
      <div style="color:var(--mut);font-size:13px">Configure o salário base:<br>
        <code>finance.sh config salario_base &lt;valor&gt;</code></div>
      {% endif %}
    </div></div>
    {% if pessoas %}<div class=card><div style="display:flex;align-items:center;margin-bottom:4px"><h3 style="margin:0;flex:1">Distribuição por pessoa (N1/N2/N3)</h3>
      <a class=tag href="{{url_for('contas')}}">editar titular →</a></div>
    <p class=tag style="margin:0 0 14px">Quanto cada pessoa gasta por essencialidade (titular da conta) — recorrentes + excepcionais, exclui movimentações. % entre N1/N2/N3.</p>
    {% set ncor = {1:'#2f81f7',2:'#3fb950',3:'#ef6c00'} %}
    {% for p in pessoas %}
    <div style="margin:0 0 16px">
      <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:5px">
        <b style="font-size:15px">{{p.nome}}</b>
        <span class=tag>N1+N2+N3 {{p.base|brl}}{% if p.n0>0 %} · sem nível {{p.n0|brl}}{% endif %}</span></div>
      <div class=pdist>
        {% for niv,val in [(1,p.n1),(2,p.n2),(3,p.n3)] if val>0 %}
        <div class=pseg style="flex:{{val}};background:{{ncor[niv]}}" title="N{{niv}}: {{val|brl}} — clique p/ ver lançamentos" data-tipo=pessoanivel data-val="{{niv}}" data-pessoa="{{p.nome}}" data-lbl="{{p.nome}} · N{{niv}}" onclick="openTx(this)">{{(val/p.base*100)|round(0)|int}}%</div>{% endfor %}
      </div>
      <div class=pleg>
        {% for niv,val,nm in [(1,p.n1,'N1 Comprometido'),(2,p.n2,'N2 Necessário'),(3,p.n3,'N3 Discricionário')] %}
        <span class=plegi data-tipo=pessoanivel data-val="{{niv}}" data-pessoa="{{p.nome}}" data-lbl="{{p.nome}} · N{{niv}}" onclick="openTx(this)" title="ver lançamentos"><i style="background:{{ncor[niv]}}"></i>{{nm}} — {{val|brl}} <b>{{(val/p.base*100)|round(0)|int}}%</b></span>{% endfor %}</div>
    </div>{% endfor %}
    <style>.pdist{display:flex;height:26px;border-radius:7px;overflow:hidden;background:var(--inbg)}
    .pseg{display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:700;min-width:0;overflow:hidden;cursor:pointer}
    .pseg:hover{filter:brightness(1.12)}
    .pleg{display:flex;gap:8px 18px;flex-wrap:wrap;font-size:12px;color:var(--mut);margin-top:7px}
    .pleg i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:middle}.pleg b{color:var(--ink)}
    .plegi{cursor:pointer}.plegi:hover{color:var(--ink)}.plegi:hover b{text-decoration:underline}</style></div>{% endif %}
    <div class=card><div style="display:flex;align-items:center;margin-bottom:6px"><h3 style="margin:0;flex:1">Despesas por grupo</h3>
      <a class=tag href="{{url_for('grupos')}}">editar grupos →</a></div>
    {% set pal=['#2f81f7','#3fb950','#ef6c00','#a371f7','#f85149','#00838f','#d29922','#6e7681','#bc8cff'] %}
    {% if grupos %}{% for r in grupos %}<div class=gbar>
      <div class=gl><span class=catlink data-tipo=grupo data-val="{{r['g']}}" onclick="openTx(this)" title="ver transações">{{r['g']}}</span></div>
      <div class=gt><div class=gf style="width:{{(r['v']/maxg*100)|round(1)}}%;background:{{pal[loop.index0 % 9]}}"></div></div>
      <div class=gv>{{r['v']|brl}} <span class=tag>{{(r['v']/totg*100)|round(0)|int}}%</span></div></div>{% endfor %}
    {% else %}<p class=muted>Sem despesas em {{mes}}. <a href="{{url_for('nova')}}">Lançar →</a></p>{% endif %}</div>
    {% if orc %}<div class=card><div style="display:flex;align-items:center;margin-bottom:6px"><h3 style="margin:0;flex:1">Orçamento do mês</h3>
      <a class=tag href="{{url_for('limites')}}">editar limites →</a></div>
    {% for r in orc %}{% set p=(r['spent']*100//r['lim']) %}<div class=gbar>
      <div class=gl>{{r['cat']}}</div>
      <div class=gt><div class=gf style="width:{{ [p,100]|min }}%;background:{{ 'var(--red)' if p>=100 else ('#d29922' if p>=80 else 'var(--grn)') }}"></div></div>
      <div class=gv>{{r['spent']|brl}}/{{r['lim']|brl}} <span class=tag>{{p}}%</span></div></div>{% endfor %}</div>{% endif %}
    {% if niv_detail %}<div class=card><h3 style=margin-top:0>Detalhe por essencialidade</h3>
    {% for nv in niv_detail %}
    <div style="display:flex;align-items:center;gap:8px;margin:14px 0 2px">
      <span style="display:inline-block;width:11px;height:11px;border-radius:3px;background:{{nv.color}}"></span>
      <b style="color:{{nv.color}}">{{nv.label}}</b>
      <b style="margin-left:auto" class=neg>{{nv.total|brl}}</b></div>
    <table style="margin-left:19px">{% for cat,v in nv['items'] %}<tr><td><span class=catlink data-tipo=cat data-val="{{cat}}" onclick="openTx(this)" title="ver transações">{{cat}}</span></td><td style=text-align:right class=neg>{{v|brl}}</td></tr>{% endfor %}</table>
    {% endfor %}</div>{% endif %}
    <style>.gbar{display:grid;grid-template-columns:130px 1fr 190px;align-items:center;gap:10px;margin:7px 0}
    .gl{font-size:14px}.gt{background:var(--inbg);border-radius:6px;height:18px;overflow:hidden}
    .gf{height:100%;border-radius:6px;min-width:2px}.gv{text-align:right;font-size:13px}
    .mchart{display:flex;align-items:flex-end;gap:16px;min-height:185px;padding-top:10px;overflow-x:auto}
    .mcol{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:46px;flex:1}
    .mbars{display:flex;align-items:flex-end;gap:3px}
    .mbar{display:flex;flex-direction:column;justify-content:flex-end;width:18px}
    .mbar>div{border-radius:3px 3px 0 0;min-height:2px}
    .mlbl{font-size:12px;color:var(--mut);margin-top:6px}.mcol.on .mlbl{color:var(--ink);font-weight:700}
    .catlink{cursor:pointer;border-bottom:1px dashed var(--mut)}.catlink:hover{color:var(--acc);border-color:var(--acc)}
    .modal{display:none;position:fixed;inset:0;background:#000a;z-index:50;align-items:flex-start;justify-content:center;padding:40px 16px;overflow:auto}
    .modal.on{display:flex}
    .modalbox{background:var(--card,#1a2230);border:1px solid var(--ln);border-radius:14px;max-width:1040px;width:100%;box-shadow:0 20px 60px #000a}
    .modalhd{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--ln);position:sticky;top:0;background:var(--card,#1a2230);border-radius:14px 14px 0 0}
    .modalhd b{flex:1}.mclose{background:transparent;border:0;color:var(--mut);font-size:18px;cursor:pointer}.mclose:hover{color:var(--red)}
    .modalbody{padding:10px 18px 18px;overflow-x:auto}</style>
    <div id=catmodal class=modal onclick="if(event.target==this)closeCat()">
      <div class=modalbox>
        <div class=modalhd><b id=catttl></b><button class=mclose onclick=closeCat() title=fechar>✕</button></div>
        <div id=catbody class=modalbody></div>
      </div></div>
    <script>
    function openTx(el){var tipo=el.dataset.tipo||'cat',val=el.dataset.val,lbl=el.dataset.lbl||val;
      var extra=el.dataset.pessoa?('&pessoa='+encodeURIComponent(el.dataset.pessoa)):'';
      document.getElementById('catttl').textContent='Transações · '+lbl+' · {{mes}}';
      document.getElementById('catbody').innerHTML='<p class=muted>Carregando…</p>';
      document.getElementById('catmodal').classList.add('on');
      fetch('/api/cat_tx?mes={{mes}}&tipo='+tipo+'&val='+encodeURIComponent(val)+extra)
        .then(function(r){return r.text();}).then(function(h){document.getElementById('catbody').innerHTML=h;})
        .catch(function(){document.getElementById('catbody').innerHTML='<p class=neg>Erro ao carregar.</p>';});}
    function closeCat(){document.getElementById('catmodal').classList.remove('on');}
    document.addEventListener('keydown',function(e){if(e.key=='Escape')closeCat();});
    </script>""" + TX_JS
    return render(inner, mes=mes, desp=desp, exc=exc, rec=rec, n=n, pend=pend, grupos=grupos, niv_detail=niv_detail, orc=orc, maxg=maxg, totg=totg, meses=meses,
                  n1=n1, n2=n2, n3=n3, n0=n0, obrigatorio=obrigatorio, salario_base=salario_base,
                  acolor=acolor, pessoas=pessoas, orcserie_json=json.dumps(orcserie))

# ---------- transações de uma categoria (modal do Resumo) ----------
@app.route("/api/cat_tx")
@login_required
def api_cat_tx():
    tipo = request.args.get("tipo", "cat")
    val = request.args.get("val", request.args.get("cat", ""))
    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    c = db()
    base = """SELECT t.*, a.name acc FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
              WHERE {w} AND substr(t.date,1,7)=? ORDER BY t.date DESC, t.id DESC"""
    # despesas que entram nos agregados de grupo/nível (não-transferência, não-excepcional)
    despesa = (" AND t.amount<0 AND COALESCE(t.excepcional,0)=0"
               " AND COALESCE(t.category,'') NOT IN (SELECT name FROM categories WHERE is_transfer=1)")
    if tipo == "grupo":
        w = "t.category IN (SELECT name FROM categories WHERE COALESCE(NULLIF(grupo,''),'(sem grupo)')=?)" + despesa
        rows = c.execute(base.format(w=w), (val, mes)).fetchall()
    elif tipo == "nivel":
        w = "COALESCE((SELECT nivel FROM categories WHERE name=t.category), t.email_hint_nivel, 0)=?" + despesa
        rows = c.execute(base.format(w=w), (int(val or 0), mes)).fetchall()
    elif tipo == "pessoanivel":
        # despesas de uma pessoa (titular da conta) num nível — recorrentes + excepcionais (não exclui excepcional)
        pessoa = request.args.get("pessoa", ""); niv = int(val or 0)
        nt = " AND t.amount<0 AND COALESCE(t.category,'') NOT IN (SELECT name FROM categories WHERE is_transfer=1)"
        nivc = " AND COALESCE((SELECT nivel FROM categories WHERE name=t.category), t.email_hint_nivel, 0)=?"
        if pessoa in ("", "(sem titular)"):
            w = "t.account_id IN (SELECT id FROM accounts WHERE titular IS NULL)" + nivc + nt
            rows = c.execute(base.format(w=w), (niv, mes)).fetchall()
        else:
            w = "t.account_id IN (SELECT id FROM accounts WHERE titular=?)" + nivc + nt
            rows = c.execute(base.format(w=w), (pessoa, niv, mes)).fetchall()
    elif val in ("(sem categoria)", "—", ""):
        rows = c.execute(base.format(w="(t.category IS NULL OR t.category='')"), (mes,)).fetchall()
    else:
        rows = c.execute(base.format(w="COALESCE(t.category,'')=?"), (val, mes)).fetchall()
    accs = c.execute("SELECT id,name,color FROM accounts ORDER BY name").fetchall()
    cat_rows = c.execute("SELECT name, COALESCE(NULLIF(grupo,''),'(sem grupo)') g FROM categories ORDER BY g, name").fetchall()
    tot = sum(r["amount"] for r in rows); c.close()
    cat_groups = {}
    for r in cat_rows: cat_groups.setdefault(r["g"], []).append(r["name"])
    acolor = {a["id"]: (a["color"] or "#888") for a in accs}
    if not rows:
        return "<p class=muted>Nenhuma transação neste recorte no mês.</p>"
    return render_template_string("<table class=txtbl>" + TX_HEAD + TX_ROWS + TX_TOTAL + "</table>",
                                  rows=rows, accs=accs, cat_groups=cat_groups, acolor=acolor,
                                  statuses=STATUSES, glyph=STATUS_GLYPH, tot=tot,
                                  totais=tot_by_currency(rows), val_label=val_label_for(rows),
                                  src_icons=SRC_ICONS, src_labels=SRC_ICONS_LABELS)

# ---------- relatório por favorecido ----------
@app.route("/favorecidos")
@login_required
def favorecidos():
    todos = request.args.get("todos"); mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    q = request.args.get("q", "").strip()
    dest = "COALESCE(NULLIF(favorecido,''),description)"
    where = ["amount<0", NOTRANSFER]; params = []
    if not todos: where.append("substr(date,1,7)=?"); params.append(mes)
    if q: where.append(f"{dest} LIKE ?"); params.append(f"%{q}%")
    c = db()
    rows = c.execute(f"""SELECT {dest} dest, COUNT(*) qt, -SUM(amount) total, MAX(COALESCE(category,'—')) cat
        FROM transactions WHERE {' AND '.join(where)} GROUP BY {dest} ORDER BY -SUM(amount) DESC""", params).fetchall()
    c.close()
    total = sum(r["total"] for r in rows); maxv = rows[0]["total"] if rows else 1
    inner = """<div class=card>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px"><h3 style="margin:0;flex:1">Despesas por favorecido</h3>
      <a class=tag href="{{url_for('favorecidos_gerir')}}">gerenciar favorecidos →</a></div>
    <form class=ffil>
      <label style="display:flex;align-items:center;gap:6px"><input type=checkbox name=todos value=1 {{'checked' if todos}} onchange=this.form.submit()> Todos os meses</label>
      {% if not todos %}<input type=month name=mes value="{{mes}}" class=fon onchange=this.form.submit()>{% endif %}
      <input name=q value="{{q}}" class="{{'fon' if q}}" placeholder="buscar favorecido…" onkeydown="if(event.key=='Enter')this.form.submit()">
      {% if q or todos %}<a href="{{url_for('favorecidos')}}" class=muted>limpar</a>{% endif %}
    </form>
    <p class=muted style=margin:4px 0 12px>{{rows|length}} favorecidos · total <b class=neg>{{total|brl}}</b>{% if not todos %} em {{mes}}{% endif %}</p>
    {% if rows %}<table class=smart><tr><th>Favorecido / Estabelecimento</th><th data-f data-g>Categoria</th><th data-t=num style=text-align:center>Qtd</th><th data-t=num data-sum style=text-align:right>Total</th><th data-nosort style=width:130px></th></tr>
    {% for r in rows %}<tr>
      <td><a href="{{url_for('favorecido_det', nome=r['dest'], mes=mes, todos=todos)}}">{{r['dest']}}</a></td><td class=tag>{{r['cat']}}</td>
      <td style=text-align:center class=tag>{{r['qt']}}×</td>
      <td style=text-align:right class=neg>{{r['total']|brl}}</td>
      <td><div class=fbar><div class=ffill style="width:{{(r['total']/maxv*100)|round(1)}}%"></div></div></td></tr>{% endfor %}
    </table>{% else %}<p class=muted>Nenhuma despesa no período.</p>{% endif %}</div>
    <style>.ffil{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:6px}.ffil>*{font-size:13px}
    .fbar{background:var(--inbg);border-radius:5px;height:8px;overflow:hidden}.ffill{height:100%;background:var(--red);border-radius:5px;min-width:2px}</style>"""
    return render(inner, rows=rows, total=total, maxv=maxv, mes=mes, todos=todos, q=q)

@app.route("/favorecido")
@login_required
def favorecido_det():
    nome = request.args.get("nome", "")
    todos = request.args.get("todos"); mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    dest = "COALESCE(NULLIF(favorecido,''),description)"
    where = [f"{dest}=?"]; params = [nome]
    if not todos: where.append("substr(date,1,7)=?"); params.append(mes)
    c = db()
    rows = c.execute(f"""SELECT t.*, a.name acc FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        WHERE {' AND '.join(where)} ORDER BY t.date DESC, t.id DESC""", params).fetchall()
    accs = c.execute("SELECT id,name,color FROM accounts ORDER BY name").fetchall()
    cat_rows = c.execute("SELECT name, COALESCE(NULLIF(grupo,''),'(sem grupo)') g FROM categories ORDER BY g, name").fetchall()
    c.close()
    cat_groups = {}
    for r in cat_rows: cat_groups.setdefault(r["g"], []).append(r["name"])
    acolor = {a["id"]: (a["color"] or "#888") for a in accs}
    tot = sum(r["amount"] for r in rows)
    inner = """<div class=card>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
      <a href="{{url_for('favorecidos')}}" class=muted>← favorecidos</a>
      <h3 style="margin:0">{{nome}}</h3></div>
    <form class=ffil><input type=hidden name=nome value="{{nome}}">
      <label style="display:flex;align-items:center;gap:6px"><input type=checkbox name=todos value=1 {{'checked' if todos}} onchange=this.form.submit()> Todos os meses</label>
      {% if not todos %}<input type=month name=mes value="{{mes}}" onchange=this.form.submit()>{% endif %}</form>
    <p class=muted style=margin:4px 0 12px>{{rows|length}} lançamentos · total <b class="{{'pos' if tot>0 else 'neg'}}">{{tot|brl}}</b>{% if not todos %} em {{mes}}{% endif %}</p>
    <table class=txtbl>""" + TX_HEAD + TX_ROWS + TX_TOTAL + """</table>
    {% if not rows %}<p class=muted>Sem lançamentos no período.</p>{% endif %}</div>
    <style>.ffil{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:6px}.ffil>*{font-size:13px}</style>
    """ + TX_JS
    return render(inner, nome=nome, rows=rows, tot=tot, totais=tot_by_currency(rows), val_label=val_label_for(rows), mes=mes, todos=todos, accs=accs, cat_groups=cat_groups, acolor=acolor, statuses=STATUSES, glyph=STATUS_GLYPH, src_icons=SRC_ICONS, src_labels=SRC_ICONS_LABELS)

FAV_TIPOS = ["", "pessoa", "empresa", "órgão público", "outro"]

@app.route("/favorecidos/gerir")
@login_required
def favorecidos_gerir():
    c = db()
    rows = c.execute("SELECT f.*, (SELECT COUNT(*) FROM transactions WHERE favorecido=f.nome) usos FROM favorecidos f ORDER BY f.nome").fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY name").fetchall()
    c.close()
    favs = []
    for r in rows:
        try: al = json.loads(r["aliases"] or "[]")
        except Exception: al = []
        favs.append({"id": r["id"], "nome": r["nome"], "tipo": r["tipo"] or "", "documento": r["documento"] or "",
                     "cp": r["categoria_padrao"] or "", "aliases": ", ".join(al), "rec": r["recorrente"] or 0, "usos": r["usos"]})
    inner = """<div class=card>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px"><h3 style="margin:0;flex:1">Favorecidos (cadastro)</h3>
      <a class=tag href="{{url_for('favorecidos')}}">← relatório</a>
      <form method=post action="{{url_for('favorecidos_aplicar')}}"><button class=btn>Aplicar (normalizar)</button></form></div>
    <p class=muted>Nome canônico do favorecido. Os <b>apelidos</b> (texto cru do extrato, separados por vírgula) são normalizados pro nome; a <b>categoria padrão</b> classifica os lançamentos automaticamente.</p>
    <datalist id=cats>{% for ct in cats %}<option value="{{ct['name']}}">{% endfor %}</datalist>
    <table id=fv class=smart><tr><th>Nome</th><th data-f data-g>Tipo</th><th>Documento</th><th data-f data-g>Categoria padrão</th><th data-f data-g>Recorrente</th><th>Apelidos (vírgula)</th><th data-t=num>Uso</th><th data-nosort></th></tr>
    <tr class="newrow skip">
      <td><input id=a_nome placeholder="+ novo favorecido…"></td>
      <td><select id=a_tipo>{% for t in tipos %}<option>{{t}}</option>{% endfor %}</select></td>
      <td><input id=a_doc placeholder="CPF/CNPJ"></td>
      <td><input id=a_cp list=cats placeholder="categoria"></td>
      <td><select id=a_rec><option value=0>Não</option><option value=1>Sim</option></select></td>
      <td><input id=a_al placeholder="apelido1, apelido2"></td>
      <td></td><td><button class=addb onclick="addf()">＋</button></td></tr>
    {% for f in favs %}<tr>
      <td><input value="{{f.nome}}" onchange="sf({{f.id}},'nome',this)"></td>
      <td><select onchange="sf({{f.id}},'tipo',this)">{% for t in tipos %}<option {{'selected' if f.tipo==t}}>{{t}}</option>{% endfor %}</select></td>
      <td><input value="{{f.documento}}" onchange="sf({{f.id}},'documento',this)"></td>
      <td><input list=cats value="{{f.cp}}" onchange="sf({{f.id}},'categoria_padrao',this)"></td>
      <td><select onchange="sf({{f.id}},'recorrente',this)"><option value=0 {{'selected' if not f.rec}}>Não</option><option value=1 {{'selected' if f.rec}}>Sim</option></select></td>
      <td><input value="{{f.aliases}}" onchange="sf({{f.id}},'aliases',this)"></td>
      <td class=tag>{{f.usos}}</td>
      <td><button class=del onclick="dlf({{f.id}})">✕</button></td></tr>{% endfor %}
    </table></div>
    <style>#fv{font-size:13px}#fv td,#fv th{padding:6px 6px}#fv input,#fv select{background:transparent;border:1px solid transparent;border-radius:6px;color:var(--ink);padding:5px 6px;width:100%;font-size:13px}
    #fv input:hover,#fv select:hover{border-color:var(--ln)}#fv input:focus,#fv select:focus{border-color:var(--acc);background:var(--inbg);outline:none}
    .saved{background:#3fb95033!important}.err{border-color:var(--red)!important}button.del{background:transparent;color:var(--mut);padding:4px 8px;font-size:14px}button.del:hover{color:var(--red)}
    button.addb{background:var(--grn);color:#fff;border:0;border-radius:6px;padding:3px 11px;cursor:pointer;font-weight:700;font-size:15px}tr.newrow{background:#2f81f714}</style>
    <script>
    function sf(id,field,el){fetch('/api/favorecido/'+id,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:'field='+field+'&value='+encodeURIComponent(el.value)}).then(r=>r.json())
      .then(j=>{el.classList.remove('err','saved');el.classList.add(j.ok?'saved':'err');setTimeout(()=>el.classList.remove('saved'),700);});}
    function addf(){var g=i=>document.getElementById(i).value;if(!g('a_nome')){alert('Informe o nome.');return;}
      var b=new URLSearchParams({nome:g('a_nome'),tipo:g('a_tipo'),documento:g('a_doc'),categoria_padrao:g('a_cp'),recorrente:g('a_rec'),aliases:g('a_al')}).toString();
      fetch('/api/favorecido/new',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:b}).then(r=>r.json()).then(j=>{if(j.ok)location.reload();else alert(j.err||'erro');});}
    function dlf(id){if(!confirm('Excluir favorecido?'))return;fetch('/api/favorecido/'+id+'/delete',{method:'POST'}).then(()=>location.reload());}
    </script>"""
    return render(inner, favs=favs, cats=cats, tipos=FAV_TIPOS)

@app.route("/api/favorecido/new", methods=["POST"])
@login_required
def api_favorecido_new():
    f = request.form; nome = (f.get("nome") or "").strip()
    if not nome: return {"ok": False, "err": "nome obrigatório"}, 400
    al = [a.strip() for a in (f.get("aliases") or "").split(",") if a.strip()]
    c = db()
    try:
        c.execute("INSERT INTO favorecidos(nome,tipo,documento,categoria_padrao,recorrente,aliases) VALUES(?,?,?,?,?,?)",
                  (nome, f.get("tipo") or None, f.get("documento") or None, f.get("categoria_padrao") or None,
                   1 if f.get("recorrente") in ("1", "true", "on") else 0, json.dumps(al, ensure_ascii=False)))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "já existe favorecido com esse nome"}, 400
    c.close(); return {"ok": True}

@app.route("/api/favorecido/<int:fid>", methods=["POST"])
@login_required
def api_favorecido(fid):
    field = request.form.get("field"); value = request.form.get("value", "").strip()
    if field not in {"nome", "tipo", "documento", "categoria_padrao", "aliases", "notas", "recorrente", "nivel_padrao"}:
        return {"ok": False, "err": "campo inválido"}, 400
    c = db()
    if field == "aliases":
        al = [a.strip() for a in value.split(",") if a.strip()]
        c.execute("UPDATE favorecidos SET aliases=? WHERE id=?", (json.dumps(al, ensure_ascii=False), fid))
    elif field == "recorrente":
        c.execute("UPDATE favorecidos SET recorrente=? WHERE id=?", (1 if value in ("1", "true", "on") else 0, fid))
    elif field == "nome" and not value:
        c.close(); return {"ok": False, "err": "nome não pode ficar vazio"}, 400
    else:
        try:
            c.execute(f"UPDATE favorecidos SET {field}=? WHERE id=?", (value or None, fid))
        except sqlite3.IntegrityError:
            c.close(); return {"ok": False, "err": "nome duplicado"}, 400
    c.commit(); c.close(); return {"ok": True}

@app.route("/api/favorecido/<int:fid>/delete", methods=["POST"])
@login_required
def api_favorecido_del(fid):
    c = db(); c.execute("DELETE FROM favorecidos WHERE id=?", (fid,)); c.commit(); c.close()
    return {"ok": True}

@app.route("/favorecidos/aplicar", methods=["POST"])
@login_required
def favorecidos_aplicar():
    c = db(); n = finance_rules.apply_favorecidos(c); c.close()
    flash(f"Normalização aplicada: {n} lançamento(s) atualizados.")
    return redirect(url_for("favorecidos_gerir"))

# ---------- listagem ----------
@app.route("/transacoes")
@login_required
def transacoes():
    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    de = request.args.get("de", "").strip(); ate = request.args.get("ate", "").strip()
    f_conta = request.args.get("conta", ""); f_cat = request.args.get("categoria", "")
    f_status = request.args.get("status", ""); q = request.args.get("q", "").strip()
    where = []; params = []
    if de or ate:                       # intervalo de datas tem prioridade sobre o mês
        if de:  where.append("t.date>=?"); params.append(de)
        if ate: where.append("t.date<=?"); params.append(ate)
    else:
        where.append("substr(t.date,1,7)=?"); params.append(mes)
    if f_conta:  where.append("t.account_id=?"); params.append(f_conta)
    if f_cat == "__sem__":
        where.append("(t.category IS NULL OR t.category='')")
    elif f_cat in ("n0", "n1", "n2", "n3"):
        where.append("t.category IN (SELECT name FROM categories WHERE COALESCE(nivel,0)=?)"); params.append(int(f_cat[1]))
    elif f_cat:
        where.append("COALESCE(t.category,'')=?"); params.append(f_cat)
    if f_status: where.append("t.status=?"); params.append(f_status)
    if q:        where.append("(t.description LIKE ? OR t.merchant LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    c = db()
    rows = c.execute(f"""SELECT t.*, a.name acc FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
                        WHERE {' AND '.join(where)} ORDER BY t.date DESC, t.id DESC""", params).fetchall()
    accs = c.execute("SELECT id,name,color FROM accounts ORDER BY name").fetchall()
    cat_rows = c.execute("SELECT name, COALESCE(NULLIF(grupo,''),'(sem grupo)') g FROM categories ORDER BY g, name").fetchall()
    tot = sum(r["amount"] for r in rows); c.close()
    cat_groups = {}
    for r in cat_rows: cat_groups.setdefault(r["g"], []).append(r["name"])
    acolor = {a["id"]: (a["color"] or "#888") for a in accs}
    inner = """<div class=card><div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
    <h3 style="margin:0;flex:1">Transações</h3></div>
    <div class=txtabs>
      {% for a in accs %}<a class="txtab{{' on' if f_conta==a['id']|string}}" style="--ac:{{acolor.get(a['id'],'var(--acc)')}}" href="{{url_for('transacoes',mes=mes,de=de,ate=ate,conta=a['id'],categoria=f_cat,status=f_status,q=q)}}">{{a['name']}}</a>{% endfor %}
      <a class="txtab{{' on' if not f_conta}}" href="{{url_for('transacoes',mes=mes,de=de,ate=ate,categoria=f_cat,status=f_status,q=q)}}">Todas</a>
    </div>
    <form class=filtros>
      <input type=month name=mes value="{{mes}}" class="{{'fon' if not (de or ate)}}" {{'disabled' if de or ate}} onchange=this.form.submit() title="mês (ignorado quando há intervalo de datas)">
      <span class=daterange>de <input type=date name=de value="{{de}}" class="{{'fon' if de}}" onchange=this.form.submit()> até <input type=date name=ate value="{{ate}}" class="{{'fon' if ate}}" onchange=this.form.submit()></span>
      {% if f_conta %}<input type=hidden name=conta value="{{f_conta}}">{% endif %}
      <select name=categoria class="{{'fon' if f_cat}}" onchange=this.form.submit()><option value="">Categoria: todas</option>
        <option value="__sem__" {{'selected' if f_cat=='__sem__'}}>— sem categoria —</option>
        <optgroup label="Por nível">
          <option value="n1" {{'selected' if f_cat=='n1'}}>N1 — Comprometido</option>
          <option value="n2" {{'selected' if f_cat=='n2'}}>N2 — Necessário variável</option>
          <option value="n3" {{'selected' if f_cat=='n3'}}>N3 — Discricionário</option>
          <option value="n0" {{'selected' if f_cat=='n0'}}>N0 — neutro</option></optgroup>
        {% for g,names in cat_groups.items() %}<optgroup label="{{g}}">
          {% for nm in names %}<option {{'selected' if f_cat==nm}}>{{nm}}</option>{% endfor %}</optgroup>{% endfor %}</select>
      <select name=status class="{{'fon' if f_status}}" onchange=this.form.submit()><option value="">Status: todos</option>
        {% for s in statuses %}<option {{'selected' if f_status==s}}>{{s}}</option>{% endfor %}</select>
      <input name=q value="{{q}}" class="{{'fon' if q}}" placeholder="buscar…" onkeydown="if(event.key=='Enter')this.form.submit()">
      {% if f_cat or f_status or q or de or ate %}<a href="{{url_for('transacoes',mes=mes,conta=f_conta)}}" class=muted>limpar</a>{% endif %}
    </form>
    <div class=slegend>
      Status: {% for s in statuses %}<b>{{glyph[s]}}</b> {{s}}{{ ' · ' if not loop.last }}{% endfor %}
      &nbsp;·&nbsp; Origem: {% for k,lbl in src_labels.items() %}<span class=srcico style="vertical-align:middle">{{ src_icons[k] | safe }}</span> {{lbl}}{{ ' · ' if not loop.last }}{% endfor %}
    </div>
    <table id=tx class=txtbl>""" + TX_HEAD + """
    <tr class="newrow skip">
      <td><input type=datetime-local id=n_date class=dt></td>
      <td><input id=n_desc placeholder="+ nova transação…"></td>
      <td><input id=n_fav placeholder="favorecido"></td>
      <td><select id=n_cat><option value="">—</option>{% for g,names in cat_groups.items() %}<optgroup label="{{g}}">{% for nm in names %}<option>{{nm}}</option>{% endfor %}</optgroup>{% endfor %}</select></td>
      {% if show_conta %}<td><select id=n_acc><option value="">—</option>{% for a in accs %}<option value="{{a['id']}}">{{a['name']}}</option>{% endfor %}</select></td>{% endif %}
      <td><select id=n_status class=stsel>{% for s in statuses %}<option value="{{s}}" {{'selected' if s=='confirmado'}}>{{glyph[s]}}</option>{% endfor %}</select></td>
      <td><input id=n_val class=val placeholder="-45,90" style=text-align:right></td>
      <td class=txact><button class=addb onclick="addtx()" title="adicionar">＋</button></td></tr>
    """ + TX_ROWS + TX_TOTAL + """</table>
    {% if not rows %}<p class=muted style=margin-top:10px>Nenhuma transação no filtro. Use a primeira linha pra adicionar.</p>{% endif %}
    </div>
    <div class=modal id=splitm>
      <div class=modalbox style=max-width:560px>
        <div class=modalhd><b>Dividir lançamento</b><button class=mclose onclick="document.getElementById('splitm').classList.remove('on')">✕</button></div>
        <div class=modalbody>
          <p class=muted style="margin:0 0 12px">Total a dividir: <b id=splittot>0,00</b> &nbsp;·&nbsp; Restante: <b id=splitrem>0,00</b></p>
          <div id=splitrows></div>
          <select id=splitopts style=display:none><option value="">—</option>{% for g,names in cat_groups.items() %}<optgroup label="{{g}}">{% for nm in names %}<option>{{nm}}</option>{% endfor %}</optgroup>{% endfor %}</select>
          <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
            <button class=spadd onclick="addSplitLine(0)">+ linha</button>
            <button id=splitsave class=spsave onclick="splitSave()">Salvar divisão</button>
          </div>
          <p class=muted style="margin:10px 0 0;font-size:12px">A 1ª parte mantém a conciliação bancária (FITID) do lançamento original. A soma das partes precisa fechar o total.</p>
        </div>
      </div>
    </div>
    <script>window.TXACC={{ (f_conta or '')|tojson }};</script>
    <style>.wrap{max-width:none}.filtros{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}.filtros>*{font-size:13px}.slegend{font-size:12px;color:var(--mut);margin-top:10px}
    .daterange{display:inline-flex;align-items:center;gap:5px;color:var(--mut);font-size:12px}.daterange input{font-size:13px}
    .txtabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--ln);margin-bottom:14px}
    .txtab{padding:8px 14px;border:1px solid var(--ln);border-bottom:0;border-radius:9px 9px 0 0;color:var(--mut);background:var(--card);margin-bottom:-1px;font-size:13px;border-top:3px solid transparent}
    .txtab:hover{color:var(--ink)}
    .txtab.on{color:var(--ink);font-weight:700;background:var(--bg);border-top:3px solid var(--ac,var(--acc))}</style>
    """ + TX_JS
    return render(inner, mes=mes, rows=rows, accs=accs, cat_groups=cat_groups, acolor=acolor,
                  statuses=STATUSES, glyph=STATUS_GLYPH, show_conta=(not f_conta),
                  f_conta=f_conta, f_cat=f_cat, f_status=f_status, q=q, tot=tot,
                  totais=tot_by_currency(rows), val_label=val_label_for(rows), de=de, ate=ate,
                  src_icons=SRC_ICONS, src_labels=SRC_ICONS_LABELS)

@app.route("/api/tx/<int:tid>", methods=["POST"])
@login_required
def api_tx(tid):
    field = request.form.get("field"); value = request.form.get("value", "")
    if field not in {"date", "datetime", "description", "merchant", "favorecido", "category", "status", "account_id", "amount", "excepcional"}:
        return {"ok": False, "err": "campo inválido"}, 400
    c = db()
    if field == "amount":
        cents = parse_cents(value)
        if cents is None: c.close(); return {"ok": False, "err": "valor inválido"}, 400
        c.execute("UPDATE transactions SET amount=? WHERE id=?", (cents, tid))
    elif field == "excepcional":
        c.execute("UPDATE transactions SET excepcional=? WHERE id=?", (1 if value in ("1", "true", "on") else 0, tid))
    elif field == "datetime":
        d, _, t = value.partition("T")
        c.execute("UPDATE transactions SET date=?, time=? WHERE id=?", (d or None, (t[:5] or None), tid))
    elif field == "account_id":
        c.execute("UPDATE transactions SET account_id=? WHERE id=?", (int(value) if value else None, tid))
    elif field == "status" and value not in STATUSES:
        c.close(); return {"ok": False, "err": "status inválido"}, 400
    else:
        c.execute(f"UPDATE transactions SET {field}=? WHERE id=?", (value or None, tid))
    c.commit(); c.close(); return {"ok": True}

@app.route("/api/tx/<int:tid>/delete", methods=["POST"])
@login_required
def api_tx_del(tid):
    c = db()
    # se for transferência vinculada, excluir o par também
    row = c.execute("SELECT transfer_pair_id FROM transactions WHERE id=?", (tid,)).fetchone()
    pair_id = row["transfer_pair_id"] if row else None
    c.execute("DELETE FROM transactions WHERE id=?", (tid,))
    if pair_id:
        c.execute("DELETE FROM transactions WHERE id=?", (pair_id,))
    c.commit(); c.close()
    return {"ok": True, "pair_deleted": bool(pair_id)}

@app.route("/api/tx/new", methods=["POST"])
@login_required
def api_tx_new():
    f = request.form
    cents = parse_cents(f.get("valor", ""))
    if cents is None or cents == 0:
        return {"ok": False, "err": "valor inválido (use - para gasto, ex: -45,90)"}, 400
    acc = f.get("account_id", "")
    dt = f.get("date") or ""
    d, _, t = dt.partition("T")
    c = db()
    cat = f.get("category") or finance_rules.classify(c, f.get("favorecido"), f.get("description"), None)
    c.execute("""INSERT INTO transactions(date,time,amount,description,favorecido,category,account_id,status,source)
                 VALUES(?,?,?,?,?,?,?,?,'manual')""",
              (d or datetime.date.today().isoformat(), (t[:5] or None), cents, f.get("description") or None,
               f.get("favorecido") or None, cat, int(acc) if acc else None,
               f.get("status") or "confirmado"))
    c.commit(); c.close()
    subprocess.run([os.path.join(ROOT, "finance_alerts.sh")], capture_output=True)
    return {"ok": True}

@app.route("/api/tx/<int:tid>/split", methods=["POST"])
@login_required
def api_tx_split(tid):
    """Lançamento composto: divide uma transação em N partes.
    A 1ª parte reaproveita a linha original (mantém external_id/FITID p/ conciliação);
    as demais são inseridas como source='split'. Todas recebem split_group=tid.
    A soma das partes precisa ser igual ao valor original (não altera o total bancário)."""
    data = request.get_json(silent=True) or {}
    parts = data.get("parts") or []
    if len(parts) < 2:
        return {"ok": False, "err": "informe ao menos 2 partes"}, 400
    cents = [parse_cents(p.get("valor", "")) for p in parts]
    if any(x is None or x == 0 for x in cents):
        return {"ok": False, "err": "valores inválidos"}, 400
    c = db()
    row = c.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if not row:
        c.close(); return {"ok": False, "err": "transação não encontrada"}, 404
    if sum(cents) != row["amount"]:
        c.close(); return {"ok": False, "err": "a soma das partes deve fechar o valor original"}, 400
    c.execute("UPDATE transactions SET amount=?, category=?, split_group=? WHERE id=?",
              (cents[0], parts[0].get("category") or None, tid, tid))
    for p, cc in list(zip(parts, cents))[1:]:
        c.execute("""INSERT INTO transactions(date,time,amount,description,merchant,favorecido,category,account_id,source,status,notes,split_group)
                     SELECT date,time,?,description,merchant,favorecido,?,account_id,'split',status,notes,? FROM transactions WHERE id=?""",
                  (cc, p.get("category") or None, tid, tid))
    c.commit(); c.close()
    return {"ok": True}

# ---------- lançamento manual ----------
@app.route("/transacoes/nova", methods=["GET", "POST"])
@login_required
def nova():
    c = db()
    accs = c.execute("SELECT id,name FROM accounts ORDER BY name").fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY name").fetchall()
    c.close()
    if request.method == "POST":
        f = request.form
        valor = f.get("valor", "").strip()
        cmd = [FINANCE_SH, "add", valor, f.get("descricao", ""),
               f.get("categoria", ""), f.get("conta", ""), f.get("data", "")]
        if f.get("tipo") == "receita": cmd.append("--receita")
        env = dict(os.environ, SOURCE="manual")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        flash(r.stdout.strip() or r.stderr.strip() or "lançado")
        return redirect(url_for("transacoes"))
    inner = """<div class="card" style=max-width:560px>
    <h3 style=margin-top:0>Novo lançamento</h3>
    <form method=post class=row>
      <div><label>Valor (R$)</label><input name=valor placeholder="45,90" required style=width:100%></div>
      <div><label>Tipo</label><select name=tipo style=width:100%><option value=despesa>Despesa</option><option value=receita>Receita</option></select></div>
      <div class=full><label>Descrição</label><input name=descricao placeholder="iFood almoço" style=width:100%></div>
      <div><label>Categoria</label><select name=categoria style=width:100%><option value="">(automática)</option>
        {% for ct in cats %}<option>{{ct['name']}}</option>{% endfor %}</select></div>
      <div><label>Conta</label><select name=conta style=width:100%><option value="">—</option>
        {% for a in accs %}<option value="{{a['id']}}">{{a['name']}}</option>{% endfor %}</select></div>
      <div><label>Data</label><input type=date name=data value="{{hoje}}" style=width:100%></div>
      <div class=full><button>Lançar</button> <a href="{{url_for('transacoes')}}" class=muted>cancelar</a></div>
    </form></div>"""
    return render(inner, accs=accs, cats=cats, hoje=datetime.date.today().isoformat())

# ---------- trocar senha ----------
@app.route("/senha", methods=["GET", "POST"])
@login_required
def senha():
    if request.method == "POST":
        atual = request.form.get("atual", ""); nova = request.form.get("nova", "")
        rec = users().get(session["user"])
        if not (rec and check_password_hash(rec["hash"], atual)):
            flash("Senha atual incorreta.")
        elif len(nova) < 6:
            flash("Nova senha muito curta (mín. 6).")
        else:
            subprocess.run(["python3", os.path.join(ROOT, "finance_user.py"),
                            "set", session["user"], session.get("role", "editor"), nova])
            flash("Senha alterada.")
        return redirect(url_for("senha"))
    inner = """<div class=card style=max-width:420px><h3 style=margin-top:0>Trocar senha</h3>
    <form method=post><label>Senha atual</label><input name=atual type=password style=width:100%>
    <label style=margin-top:10px>Nova senha</label><input name=nova type=password style=width:100%>
    <button style=margin-top:14px>Salvar</button></form></div>"""
    return render(inner)

RULE_FIELDS = [("favorecido", "Favorecido"), ("description", "Descrição"),
               ("merchant", "Estabelecimento"), ("qualquer", "Qualquer campo")]

def ensure_category(c, name):
    if name and not c.execute("SELECT 1 FROM categories WHERE name=?", (name,)).fetchone():
        c.execute("INSERT INTO categories(name,icon) VALUES(?, '🏷️')", (name,))

@app.route("/regras")
@login_required
def regras():
    c = db()
    rows = c.execute("SELECT * FROM rules ORDER BY id").fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY name").fetchall()
    accs = c.execute("SELECT id,name FROM accounts ORDER BY name").fetchall()
    c.close()
    inner = """<div class=card>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <h3 style="margin:0;flex:1">Regras de classificação</h3>
      <form method=post action="{{url_for('regras_aplicar')}}"><button class=btn>Aplicar às transações</button></form></div>
    <p class=muted>Quando o campo escolhido <b>contém</b> o texto, a transação recebe a categoria. Restrições opcionais: <b>Conta</b> (só naquela conta) e <b>Dias</b> (dia do mês entre mín–máx — útil p/ débito automático, absorve fim de semana / próximo dia útil / variação de ciclo). <b>→ favorecido</b> (opcional) preenche o favorecido quando estiver vazio. Ex.: <i>Descrição</i> contém <i>Débito em conta</i>, conta <i>Nu Rodrigo</i>, dias <i>7–13</i> → <i>Energia elétrica</i> / <i>Energisa</i>. As regras valem p/ lançamentos novos e extratos importados; o botão acima reaplica nas já existentes.</p>
    <datalist id=cats>{% for ct in cats %}<option value="{{ct['name']}}">{% endfor %}</datalist>
    <table id=rl class=smart><tr><th data-f data-g>Campo</th><th>contém</th><th data-nosort>Conta</th><th data-nosort>Dias</th><th data-f data-g>→ categoria</th><th data-nosort>→ favorecido</th><th data-nosort></th></tr>
    <tr class="newrow skip">
      <td><select id=r_field>{% for v,lbl in fields %}<option value="{{v}}">{{lbl}}</option>{% endfor %}</select></td>
      <td><input id=r_pat placeholder="ex: Joane"></td>
      <td><select id=r_acc><option value="">qualquer</option>{% for a in accs %}<option value="{{a['id']}}">{{a['name']}}</option>{% endfor %}</select></td>
      <td><span class=dayrange><input id=r_dmin type=number min=1 max=31 placeholder=mín><input id=r_dmax type=number min=1 max=31 placeholder=máx></span></td>
      <td><input id=r_cat list=cats placeholder="ex: Doméstica"></td>
      <td><input id=r_fav placeholder="(opcional)"></td>
      <td><button class=addb onclick="addr()" title=adicionar>＋</button></td></tr>
    {% for r in rows %}<tr>
      <td><select onchange="sr({{r['id']}},'field',this)">{% for v,lbl in fields %}<option value="{{v}}" {{'selected' if r['field']==v}}>{{lbl}}</option>{% endfor %}</select></td>
      <td><input value="{{r['pattern']}}" onchange="sr({{r['id']}},'pattern',this)"></td>
      <td><select onchange="sr({{r['id']}},'account_id',this)"><option value="">qualquer</option>{% for a in accs %}<option value="{{a['id']}}" {{'selected' if r['account_id']==a['id']}}>{{a['name']}}</option>{% endfor %}</select></td>
      <td><span class=dayrange><input type=number min=1 max=31 value="{{r['dom_min'] if r['dom_min'] is not none else ''}}" onchange="sr({{r['id']}},'dom_min',this)" placeholder="–"><input type=number min=1 max=31 value="{{r['dom_max'] if r['dom_max'] is not none else ''}}" onchange="sr({{r['id']}},'dom_max',this)" placeholder="–"></span></td>
      <td><input list=cats value="{{r['category']}}" onchange="sr({{r['id']}},'category',this)"></td>
      <td><input value="{{r['set_fav'] or ''}}" onchange="sr({{r['id']}},'set_fav',this)" placeholder="—"></td>
      <td><button class=del onclick="dlr({{r['id']}})" title=excluir>✕</button></td></tr>{% endfor %}
    </table>{% if not rows %}<p class=muted style=margin-top:10px>Nenhuma regra ainda. Use a primeira linha.</p>{% endif %}</div>
    <style>#rl{font-size:13px}#rl td,#rl th{padding:6px 6px}#rl input,#rl select{background:transparent;border:1px solid transparent;border-radius:6px;color:var(--ink);padding:5px 6px;width:100%;font-size:13px}
    #rl input:hover,#rl select:hover{border-color:var(--ln)}#rl input:focus,#rl select:focus{border-color:var(--acc);background:var(--inbg);outline:none}
    #rl .dayrange{display:flex;gap:3px}#rl .dayrange input{width:48px;text-align:center}
    .saved{background:#3fb95033!important}.err{border-color:var(--red)!important}
    button.del{background:transparent;color:var(--mut);padding:4px 8px;font-size:14px}button.del:hover{color:var(--red)}
    button.addb{background:var(--grn);color:#fff;border:0;border-radius:6px;padding:3px 11px;cursor:pointer;font-weight:700;font-size:15px}
    tr.newrow{background:#2f81f714}</style>
    <script>
    function sr(id,field,el){fetch('/api/rule/'+id,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:'field='+field+'&value='+encodeURIComponent(el.value)}).then(r=>r.json())
      .then(j=>{el.classList.remove('err','saved');el.classList.add(j.ok?'saved':'err');setTimeout(()=>el.classList.remove('saved'),700);});}
    function addr(){const g=i=>document.getElementById(i).value;
      if(!g('r_pat')||!g('r_cat')){alert('Preencha o texto e a categoria.');return;}
      const b=new URLSearchParams({field:g('r_field'),pattern:g('r_pat'),category:g('r_cat'),
        conta:g('r_acc'),dom_min:g('r_dmin'),dom_max:g('r_dmax'),set_fav:g('r_fav')}).toString();
      fetch('/api/rule/new',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:b})
      .then(r=>r.json()).then(j=>{if(j.ok)location.reload();else alert(j.err||'erro');});}
    function dlr(id){if(!confirm('Excluir regra?'))return;fetch('/api/rule/'+id+'/delete',{method:'POST'}).then(()=>location.reload());}
    </script>"""
    return render(inner, rows=rows, cats=cats, accs=accs, fields=RULE_FIELDS)

@app.route("/api/rule/new", methods=["POST"])
@login_required
def api_rule_new():
    f = request.form
    field = f.get("field", "favorecido"); pattern = (f.get("pattern") or "").strip(); category = (f.get("category") or "").strip()
    if not pattern or not category: return {"ok": False, "err": "preencha texto e categoria"}, 400
    if field not in {"favorecido", "description", "merchant", "qualquer"}: field = "favorecido"
    def _int(v):
        v = (v or "").strip(); return int(v) if v.isdigit() else None
    acc = _int(f.get("conta")); dmin = _int(f.get("dom_min")); dmax = _int(f.get("dom_max"))
    sfav = (f.get("set_fav") or "").strip() or None
    c = db()
    ensure_category(c, category)
    c.execute("INSERT INTO rules(field,pattern,category,account_id,dom_min,dom_max,set_fav) VALUES(?,?,?,?,?,?,?)",
              (field, pattern, category, acc, dmin, dmax, sfav))
    c.commit(); c.close(); return {"ok": True}

@app.route("/api/rule/<int:rid>", methods=["POST"])
@login_required
def api_rule(rid):
    field = request.form.get("field"); value = request.form.get("value", "").strip()
    if field not in {"field", "pattern", "category", "account_id", "dom_min", "dom_max", "set_fav"}:
        return {"ok": False, "err": "campo inválido"}, 400
    if field in ("pattern", "category") and not value: return {"ok": False, "err": "não pode ficar vazio"}, 400
    c = db()
    if field == "category": ensure_category(c, value)
    if field in ("account_id", "dom_min", "dom_max"):
        c.execute(f"UPDATE rules SET {field}=? WHERE id=?", (int(value) if value.isdigit() else None, rid))
    elif field == "set_fav":
        c.execute("UPDATE rules SET set_fav=? WHERE id=?", (value or None, rid))
    else:
        c.execute(f"UPDATE rules SET {field}=? WHERE id=?", (value, rid))
    c.commit(); c.close()
    return {"ok": True}

@app.route("/api/rule/<int:rid>/delete", methods=["POST"])
@login_required
def api_rule_del(rid):
    c = db(); c.execute("DELETE FROM rules WHERE id=?", (rid,)); c.commit(); c.close()
    return {"ok": True}

@app.route("/regras/aplicar", methods=["POST"])
@login_required
def regras_aplicar():
    c = db(); n = finance_rules.apply_rules(c); c.close()
    flash(f"Regras aplicadas: {n} transação(ões) reclassificada(s).")
    return redirect(url_for("regras"))


@app.route("/limites")
@login_required
def limites():
    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    c = db()
    rows = c.execute("""SELECT cat.name, cat.icon, COALESCE(b.limit_amount,0) lim,
        COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=cat.name AND amount<0 AND substr(date,1,7)=?),0) spent
        FROM categories cat LEFT JOIN budgets b ON b.category=cat.name AND b.month='*'
        WHERE cat.name<>'Receitas' ORDER BY (CASE WHEN b.limit_amount>0 THEN 0 ELSE 1 END), cat.name""", (mes,)).fetchall()
    c.close()
    inner = """<div class=card style=max-width:680px>
    <h3 style=margin-top:0>Limites mensais por categoria</h3>
    <p class=muted>Defina quanto pretende gastar por mês em cada categoria. Quando o gasto do mês chegar a <b>80%</b> e a <b>100%</b>, você recebe um alerta no Telegram. Deixe em branco pra não ter limite.</p>
    <table class=smart><tr><th data-g>Categoria</th><th data-t=num style=width:130px>Limite (R$)</th><th data-nosort>Mês atual</th></tr>
    {% for r in rows %}<tr>
      <td>{{r['icon']}} {{r['name']}}</td>
      <td><input value="{{ r['lim']|reais_plain if r['lim'] else '' }}" placeholder="—" onchange="sl('{{r['name']}}',this)"
        style="width:110px;background:var(--inbg);border:1px solid var(--ln);border-radius:7px;color:var(--ink);padding:7px;text-align:right"></td>
      <td>{% if r['lim'] %}{% set p=(r['spent']*100//r['lim']) %}
        <div class=pbar><div class=pfill style="width:{{ [p,100]|min }}%;background:{{ 'var(--red)' if p>=100 else ('#d29922' if p>=80 else 'var(--grn)') }}"></div></div>
        <span class=tag>{{r['spent']|brl}} · {{p}}%</span>
      {% else %}<span class=muted>{{r['spent']|brl}} (sem limite)</span>{% endif %}</td></tr>{% endfor %}
    </table></div>
    <style>.pbar{background:var(--inbg);border-radius:5px;height:8px;overflow:hidden;margin-bottom:3px}.pfill{height:100%;border-radius:5px;min-width:2px}</style>
    <script>function sl(name,el){fetch('/api/limite',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:'name='+encodeURIComponent(name)+'&value='+encodeURIComponent(el.value)})
      .then(r=>r.json()).then(j=>{el.style.borderColor=j.ok?'var(--grn)':'var(--red)';if(j.ok)setTimeout(()=>location.reload(),500);});}</script>"""
    return render(inner, rows=rows, mes=mes)

@app.route("/api/limite", methods=["POST"])
@login_required
def api_limite():
    name = request.form.get("name", ""); value = request.form.get("value", "").strip()
    mes = datetime.date.today().strftime("%Y-%m")
    c = db()
    if not value:
        c.execute("DELETE FROM budgets WHERE category=? AND month='*'", (name,))
        c.execute("DELETE FROM budget_alerts WHERE category=?", (name,))
    else:
        cents = parse_cents(value)
        if cents is None: c.close(); return {"ok": False, "err": "valor inválido"}, 400
        c.execute("""INSERT INTO budgets(category,month,limit_amount) VALUES(?,'*',?)
                     ON CONFLICT(category,month) DO UPDATE SET limit_amount=excluded.limit_amount""", (name, abs(cents)))
        c.execute("DELETE FROM budget_alerts WHERE category=? AND month=?", (name, mes))  # permite re-alertar com novo limite
    c.commit(); c.close(); return {"ok": True}


ACCT_TYPES = ["corrente", "poupança", "credito", "espécie", "vale", "investimento", "conta"]

@app.route("/contas")
@login_required
def contas():
    c = db()
    rows = c.execute("""
        SELECT a.*,
               COALESCE(a.opening_balance,0) + COALESCE(SUM(t.amount),0) AS saldo,
               COALESCE(a.currency,'BRL') AS moeda,
               COUNT(t.id) AS usos
        FROM accounts a
        LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY a.id ORDER BY a.name""").fetchall()
    c.close()
    CURRENCIES = ["BRL","USD","EUR","GBP","ARS","UYU"]
    # patrimônio por moeda
    saldos_map = {}
    for r in rows:
        saldos_map[r["moeda"]] = saldos_map.get(r["moeda"], 0) + r["saldo"]
    saldos = sorted(saldos_map.items())
    # dados p/ o modal de edição
    accts = {r["id"]: {"id": r["id"], "name": r["name"] or "", "titular": r["titular"] or "",
                       "bank": r["bank"] or "", "numero": r["numero"] or "", "type": r["type"] or "corrente",
                       "currency": r["moeda"], "color": r["color"] or "#2f81f7",
                       "opening_balance": r["opening_balance"] or 0,
                       "iof_rate": r["iof_rate"] or 0, "spread_rate": r["spread_rate"] or 0,
                       "entra_orcamento": 1 if (r["entra_orcamento"] is None or r["entra_orcamento"]) else 0} for r in rows}
    inner = """<div class=card>
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px">
      <h3 style="margin:0;flex:1">Contas</h3>
      <button onclick="openNew()" style="background:var(--grn);border:0;border-radius:8px;padding:8px 16px;font-weight:700;cursor:pointer">＋ Nova conta</button>
      <a href="{{url_for('transferencia')}}" class=muted>↔ Transferência</a>
      <a href="{{url_for('investimentos')}}" class=muted>📈 Investimentos</a>
    </div>
    <p class=muted style="margin:0 0 12px">Saldo = saldo inicial + soma das transações vinculadas. Clique em ✎ para editar.</p>
    <table id=acc class=smart>
    <tr><th>Nome</th><th data-f data-g>Titular</th><th data-f data-g>Banco</th><th data-f data-g>Tipo</th><th data-f>Moeda</th><th data-t=num style=text-align:right>Saldo atual</th><th data-t=num style=text-align:right>Uso</th><th data-nosort></th></tr>
    {% for r in rows %}<tr>
      <td><span class=cdot style="background:{{r['color'] or '#888'}}"></span>{{r['name']}}</td>
      <td>{{r['titular'] or '—'}}</td>
      <td>{{r['bank'] or '—'}}</td>
      <td>{{r['type'] or '—'}}</td>
      <td>{{r['moeda']}}{% if (r['iof_rate'] or 0) or (r['spread_rate'] or 0) %}<span class=rtag title="IOF {{'%.2f'|format((r['iof_rate'] or 0)*100)}}% · Spread {{'%.2f'|format((r['spread_rate'] or 0)*100)}}%">· IOF {{'%g'|format((r['iof_rate'] or 0)*100)}}%</span>{% endif %}{% if r['entra_orcamento']==0 %}<span class=rtag title="não entra no orçamento">· fora do orç.</span>{% endif %}</td>
      <td style="text-align:right;font-weight:700" class="{{'pos' if r['saldo']>=0 else 'neg'}}">{{r['saldo']|money(r['moeda'])}}</td>
      <td style="text-align:right" class=tag>{{r['usos']}}</td>
      <td style="text-align:right;white-space:nowrap"><button class=icob onclick="openEdit({{r['id']}})" title=editar>✎</button><button class=icob onclick="delAcc({{r['id']}},{{r['usos']}})" title=excluir>✕</button></td>
    </tr>{% endfor %}
    {% for cur,val in saldos %}<tr class="totrow skip"><td colspan=4></td><td style=text-align:right class=muted>Patrimônio{% if saldos|length>1 %} {{cur}}{% endif %}</td><td style="text-align:right;font-weight:700" class="{{'pos' if val>=0 else 'neg'}}">{{val|money(cur)}}</td><td></td><td></td></tr>{% endfor %}
    </table></div>

    <div class=modal id=accmodal onclick="if(event.target==this)closeAcc()">
      <div class=modalbox>
        <div class=modalhd><b id=accttl>Editar conta</b><button class=mclose onclick=closeAcc() title=fechar>✕</button></div>
        <div class=modalbody>
          <input type=hidden id=m_id>
          <div class=mgrid>
            <div class=full><label>Nome</label><input id=m_name></div>
            <div><label>Titular</label><select id=m_titular><option value="">—</option>{% for t in titulares %}<option>{{t}}</option>{% endfor %}</select></div>
            <div><label>Banco</label><input id=m_bank></div>
            <div><label>Número</label><input id=m_num></div>
            <div><label>Tipo</label><select id=m_type>{% for t in types %}<option>{{t}}</option>{% endfor %}</select></div>
            <div><label>Moeda</label><select id=m_curr onchange=toggleRates()>{% for cur in currencies %}<option>{{cur}}</option>{% endfor %}</select></div>
            <div><label>Cor</label><input type=color id=m_color style="height:38px;padding:2px"></div>
            <div><label>Saldo inicial</label><input type=number step=0.01 id=m_ob></div>
            <div id=m_iofwrap><label>IOF %</label><input type=number step=0.01 id=m_iof></div>
            <div id=m_spreadwrap><label>Spread %</label><input type=number step=0.01 id=m_spread></div>
            <div class=full style="display:flex;align-items:center;gap:8px;margin-top:2px">
              <input type=checkbox id=m_orc style="width:auto"><label for=m_orc style="margin:0;cursor:pointer">Entra no orçamento (receitas/despesas/teto)</label></div>
          </div>
          <div style="display:flex;gap:10px;margin-top:18px;justify-content:flex-end">
            <button onclick=closeAcc() style="background:transparent;border:1px solid var(--ln);color:var(--ink)">Cancelar</button>
            <button onclick=saveAcc()>Salvar</button>
          </div>
        </div>
      </div>
    </div>

    <style>
    #acc td,#acc th{padding:9px 10px}
    .cdot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;vertical-align:middle}
    .rtag{color:var(--mut);font-size:12px;margin-left:6px}
    tr.totrow td{border-top:2px solid var(--ln);background:#8881}
    .icob{background:transparent;border:0;color:var(--mut);padding:4px 7px;font-size:14px;cursor:pointer}.icob:hover{color:var(--acc)}
    .mgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.mgrid .full{grid-column:1/-1}
    .mgrid label{display:block;font-size:12px;color:var(--mut);margin-bottom:4px;font-weight:600}
    .mgrid input,.mgrid select{width:100%}
    </style>
    <script>
    window.ACCTS = {{ accts_json|safe }};
    function _g(i){return document.getElementById(i);}
    function fill(a){a=a||{};_g('m_id').value=a.id||'';_g('m_name').value=a.name||'';_g('m_titular').value=a.titular||'';
      _g('m_bank').value=a.bank||'';_g('m_num').value=a.numero||'';_g('m_type').value=a.type||'corrente';
      _g('m_curr').value=a.currency||'BRL';_g('m_color').value=a.color||'#2f81f7';
      _g('m_ob').value=((a.opening_balance||0)/100).toFixed(2);
      _g('m_iof').value=((a.iof_rate||0)*100).toFixed(2);_g('m_spread').value=((a.spread_rate||0)*100).toFixed(2);
      _g('m_orc').checked=(a.entra_orcamento===undefined?true:!!a.entra_orcamento);
      toggleRates();}
    function toggleRates(){var multi=_g('m_curr').value!=='BRL';_g('m_iofwrap').style.display=multi?'':'none';_g('m_spreadwrap').style.display=multi?'':'none';}
    function openEdit(id){fill(ACCTS[id]);_g('accttl').textContent='Editar conta';_g('accmodal').classList.add('on');}
    function openNew(){fill(null);_g('accttl').textContent='Nova conta';_g('accmodal').classList.add('on');_g('m_name').focus();}
    function closeAcc(){_g('accmodal').classList.remove('on');}
    function saveAcc(){var id=_g('m_id').value;
      if(!_g('m_name').value.trim()){alert('Informe o nome da conta.');return;}
      var ob=Math.round((parseFloat((_g('m_ob').value||'0').replace(',','.'))||0)*100);
      var body=new URLSearchParams({name:_g('m_name').value,titular:_g('m_titular').value,bank:_g('m_bank').value,
        numero:_g('m_num').value,type:_g('m_type').value,currency:_g('m_curr').value,color:_g('m_color').value,
        opening_balance:ob,iof_rate:_g('m_iof').value||'0',spread_rate:_g('m_spread').value||'0',
        entra_orcamento:_g('m_orc').checked?'1':'0'}).toString();
      var url=id?('/api/account/'+id+'/save'):'/api/account/new';
      fetch(url,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:body})
        .then(r=>r.json()).then(j=>{if(j.ok)location.reload();else alert(j.err||'erro');});}
    function delAcc(id,usos){if(!confirm(usos>0?('Esta conta tem '+usos+' transações; elas ficarão sem conta. Excluir?'):'Excluir conta?'))return;
      fetch('/api/account/'+id+'/delete',{method:'POST'}).then(()=>location.reload());}
    </script>"""
    return render(inner, rows=rows, saldos=saldos, types=ACCT_TYPES, titulares=TITULARES,
                  currencies=CURRENCIES, accts_json=json.dumps(accts))

@app.route("/api/account/new", methods=["POST"])
@login_required
def api_account_new():
    f = request.form; name = (f.get("name") or "").strip()
    if not name: return {"ok": False, "err": "nome obrigatório"}, 400
    ob_raw = f.get("opening_balance", "0")
    try: ob = int(ob_raw)
    except: ob = 0
    currency = (f.get("currency") or "BRL").strip().upper() or "BRL"
    iof = _pct_frac(f.get("iof_rate")); spread = _pct_frac(f.get("spread_rate"))
    orc = 0 if f.get("entra_orcamento", "1") in ("0", "false", "off") else 1
    c = db()
    try:
        c.execute("INSERT INTO accounts(name,bank,numero,type,color,titular,opening_balance,currency,iof_rate,spread_rate,entra_orcamento) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (name, f.get("bank") or None, f.get("numero") or None, f.get("type") or "conta",
                   f.get("color") or "#888", f.get("titular") or None, ob, currency, iof, spread, orc))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "já existe conta com esse nome"}, 400
    c.close(); return {"ok": True}

def _pct_frac(v):   # "3,5" (percentual) -> 0.035 (fração)
    try: return float((v or "0").replace(",", ".")) / 100.0
    except: return 0.0

@app.route("/api/account/<int:aid>/save", methods=["POST"])
@login_required
def api_account_save(aid):
    f = request.form; name = (f.get("name") or "").strip()
    if not name: return {"ok": False, "err": "nome obrigatório"}, 400
    try: ob = int(f.get("opening_balance") or 0)
    except: ob = 0
    currency = (f.get("currency") or "BRL").strip().upper() or "BRL"
    c = db()
    try:
        orc = 0 if f.get("entra_orcamento", "1") in ("0", "false", "off") else 1
        c.execute("""UPDATE accounts SET name=?, titular=?, bank=?, numero=?, type=?, color=?,
                     currency=?, opening_balance=?, iof_rate=?, spread_rate=?, entra_orcamento=? WHERE id=?""",
                  (name, f.get("titular") or None, f.get("bank") or None, f.get("numero") or None,
                   f.get("type") or "conta", f.get("color") or "#888", currency, ob,
                   _pct_frac(f.get("iof_rate")), _pct_frac(f.get("spread_rate")), orc, aid))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "nome duplicado"}, 400
    c.close(); return {"ok": True}

@app.route("/api/account/<int:aid>", methods=["POST"])
@login_required
def api_account(aid):
    field = request.form.get("field"); value = request.form.get("value", "").strip()
    if field not in {"name", "bank", "numero", "type", "color", "titular", "currency", "opening_balance", "iof_rate", "spread_rate"}:
        return {"ok": False, "err": "campo inválido"}, 400
    if field == "name" and not value:
        return {"ok": False, "err": "nome não pode ficar vazio"}, 400
    c = db()
    try:
        if field == "opening_balance":
            try: v = int(value)
            except: c.close(); return {"ok": False, "err": "valor inválido"}, 400
            c.execute("UPDATE accounts SET opening_balance=? WHERE id=?", (v, aid))
        elif field in ("iof_rate", "spread_rate"):
            try: v = float((value or "0").replace(",", ".")) / 100.0   # UI em %, armazena fração
            except: c.close(); return {"ok": False, "err": "taxa inválida"}, 400
            c.execute(f"UPDATE accounts SET {field}=? WHERE id=?", (v, aid))
        elif field == "currency":
            c.execute("UPDATE accounts SET currency=? WHERE id=?", (value.upper() or "BRL", aid))
        else:
            c.execute(f"UPDATE accounts SET {field}=? WHERE id=?", (value or None, aid))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "nome duplicado"}, 400
    c.close(); return {"ok": True}

@app.route("/api/account/<int:aid>/delete", methods=["POST"])
@login_required
def api_account_del(aid):
    c = db()
    c.execute("UPDATE transactions SET account_id=NULL WHERE account_id=?", (aid,))
    c.execute("DELETE FROM accounts WHERE id=?", (aid,)); c.commit(); c.close()
    return {"ok": True}


@app.route("/grupos")
@login_required
def grupos():
    c = db()
    cats = c.execute("SELECT name, icon, grupo, is_transfer, COALESCE(nivel,0) nivel FROM categories ORDER BY COALESCE(grupo,'zzz'), name").fetchall()
    gs = [r[0] for r in c.execute("SELECT DISTINCT grupo FROM categories WHERE grupo IS NOT NULL AND grupo<>'' ORDER BY grupo")]
    c.close()
    inner = """<div class=card>
    <h3 style=margin-top:0>Grupos e níveis de despesa</h3>
    <p class=muted>
      <b>Grupo:</b> agrupa categorias no resumo mensal.<br>
      <b>Nível:</b> classifica a obrigatoriedade — <b style="color:#2f81f7">N1 Comprometido</b> (fixo/contrato),
      <b style="color:#3fb950">N2 Necessário variável</b> (todo mês, valor oscila),
      <b style="color:#ef6c00">N3 Discricionário</b> (quando sobra). N0 = movimentação ou receita.<br>
      Marque <b>Movimentação</b> quando NÃO for gasto/receita — essas não entram nos totais.
    </p>
    <datalist id=grps>{% for g in gs %}<option value="{{g}}">{% endfor %}</datalist>
    <table id=gtbl><tr>
      <th onclick="sortBy(this,'cat')" style=cursor:pointer>Categoria <span class=sc></span></th>
      <th onclick="sortBy(this,'grupo')" style=cursor:pointer>Grupo <span class=sc></span></th>
      <th onclick="sortBy(this,'nivel')" style="cursor:pointer;text-align:center">Nível <span class=sc></span></th>
      <th onclick="sortBy(this,'transfer')" style="cursor:pointer;text-align:center">Movimentação <span class=sc></span><br><span class=tag>(não é gasto)</span></th></tr>
    {% set ncores = {0:'#6e7681',1:'#2f81f7',2:'#3fb950',3:'#ef6c00'} %}
    {% set nlabels = {0:'N0',1:'N1',2:'N2',3:'N3'} %}
    {% set nfull = {0:'Neutro (movimentação/receita)',1:'Comprometido (fixo/contrato)',2:'Necessário variável',3:'Discricionário'} %}
    {% for c in cats %}<tr><td>{{c['name']}}</td>
      <td><input list=grps value="{{c['grupo'] or ''}}" placeholder="(sem grupo)" {{'disabled' if c['is_transfer']}}
        onchange="sg('{{c['name']}}',this)" style="width:100%;background:var(--inbg);border:1px solid var(--ln);border-radius:7px;color:var(--ink);padding:7px"></td>
      <td style=text-align:center><span class=pills>
        {% for v in [0,1,2,3] %}<button type=button class="pill{{' on' if c['nivel']==v}}" style="--pc:{{ncores[v]}}" title="{{nfull[v]}}" onclick="sn(this,'{{c['name']}}',{{v}})">{{nlabels[v]}}</button>{% endfor %}
      </span></td>
      <td style=text-align:center><input type=checkbox {{'checked' if c['is_transfer']}} onchange="st('{{c['name']}}',this)"></td></tr>{% endfor %}
    </table></div>
    <style>.pills{display:inline-flex;gap:3px}
    .pill{background:transparent;border:1px solid var(--ln);color:var(--mut);border-radius:7px;padding:4px 9px;font-size:12px;font-weight:700;cursor:pointer;min-width:32px;transition:all .12s}
    .pill:hover{border-color:var(--pc);color:var(--pc)}
    .pill.on{background:var(--pc);border-color:var(--pc);color:#fff}</style>
    <script>function post(name,field,value,el){fetch('/api/cat',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:'name='+encodeURIComponent(name)+'&field='+field+'&value='+encodeURIComponent(value)})
      .then(r=>r.json()).then(j=>{if(el)el.style.borderColor=j.ok?'var(--grn)':'var(--red)';setTimeout(()=>{if(el)el.style.borderColor='var(--ln)'},800);});}
    function sg(name,el){post(name,'grupo',el.value,el);}
    function st(name,el){post(name,'is_transfer',el.checked?1:0,null);location.reload();}
    function sn(el,name,v){var box=el.parentNode;box.querySelectorAll('.pill').forEach(function(b){b.classList.remove('on');});el.classList.add('on');post(name,'nivel',v,null);}
    var _sd={};
    function sortBy(th,key){var t=document.getElementById('gtbl');var rows=Array.prototype.slice.call(t.rows,1);
      _sd[key]=!_sd[key];var dir=_sd[key]?1:-1;
      function val(r){if(key=='cat')return r.cells[0].textContent.trim().toLowerCase();
        if(key=='grupo')return (r.querySelector('input[list=grps]').value||'~~~').toLowerCase();
        if(key=='nivel'){var p=r.querySelector('.pill.on');return p?parseInt(p.textContent.replace('N','')):0;}
        return r.querySelector('input[type=checkbox]').checked?1:0;}
      function cat(r){return r.cells[0].textContent.trim().toLowerCase();}
      rows.sort(function(a,b){var va=val(a),vb=val(b);if(va<vb)return -dir;if(va>vb)return dir;return cat(a)<cat(b)?-1:cat(a)>cat(b)?1:0;});
      rows.forEach(function(r){t.appendChild(r);});
      var hs=t.querySelectorAll('.sc');for(var i=0;i<hs.length;i++)hs[i].textContent='';
      th.querySelector('.sc').textContent=dir>0?'▲':'▼';}</script>"""
    return render(inner, cats=cats, gs=gs)

@app.route("/api/cat", methods=["POST"])
@login_required
def api_cat():
    name = request.form.get("name", ""); field = request.form.get("field", "grupo"); value = request.form.get("value", "").strip()
    c = db()
    if field == "is_transfer":
        c.execute("UPDATE categories SET is_transfer=? WHERE name=?", (1 if value in ("1", "true", "on") else 0, name))
    elif field == "grupo":
        c.execute("UPDATE categories SET grupo=? WHERE name=?", (value or None, name))
    elif field == "nivel":
        try:
            n = int(value)
            if n not in (0, 1, 2, 3): raise ValueError()
            c.execute("UPDATE categories SET nivel=? WHERE name=?", (n, name))
        except ValueError:
            c.close(); return {"ok": False, "err": "nivel inválido (0-3)"}, 400
    else:
        c.close(); return {"ok": False, "err": "campo inválido"}, 400
    c.commit(); c.close(); return {"ok": True}


@app.route("/conciliacao", methods=["GET", "POST"])
@login_required
def conciliacao():
    c = db()
    if request.method == "POST":
        f = request.files.get("ofx")
        if not f or not f.filename:
            flash("Selecione um arquivo OFX."); c.close(); return redirect(url_for("conciliacao"))
        raw = ofx_parser.decode_ofx(f.read())
        txns = ofx_parser.parse(raw)
        matched, imported, dup = ofx_parser.reconcile(c, txns, ofx_parser.parse_account(raw))
        c.execute("INSERT INTO ofx_imports(filename,matched,unmatched) VALUES(?,?,?)",
                  (f.filename, matched, imported)); c.commit()
        flash(f"OFX “{f.filename}”: {len(txns)} lidas · {matched} conciliadas · {imported} novas · {dup} já existentes")
        c.close()
        fin = os.path.join(ROOT, "finance.sh")
        subprocess.run([fin, "classify-all"], capture_output=True)   # classifica todas
        subprocess.run(["python3", os.path.join(ROOT, "finance_rules.py"), "favorecidos"], capture_output=True)  # normaliza favorecidos
        subprocess.run([fin, "ask-pending"], capture_output=True)    # pergunta o que não reconheceu
        return redirect(url_for("conciliacao"))
    last = c.execute("SELECT * FROM ofx_imports ORDER BY id DESC LIMIT 6").fetchall()
    nimp = c.execute("SELECT COUNT(*) FROM transactions WHERE status='importado'").fetchone()[0]
    ncon = c.execute("SELECT COUNT(*) FROM transactions WHERE status='conciliado'").fetchone()[0]
    c.close()
    inner = """<div class=card style=max-width:560px>
    <h3 style=margin-top:0>Conciliação bancária (OFX)</h3>
    <p class=muted>Envie o extrato OFX do banco. Eu caso cada lançamento com o que já existe (mesmo valor, data ±2 dias) e marco como <b>conciliado</b>; o que não casar entra como <b>importado</b> pra você revisar.</p>
    <form method=post enctype=multipart/form-data style="display:flex;gap:10px;align-items:center">
      <input type=file name=ofx accept=".ofx,.qfx,text/*" required><button>Importar</button></form></div>
    <div class=grid style=margin-top:16px>
      <div class="card kpi"><div class=l>A revisar (importado)</div><div class=v>{{nimp}}</div>
        {% if nimp %}<div class=tag><a href="{{url_for('transacoes',status='importado')}}">revisar →</a></div>{% endif %}</div>
      <div class="card kpi"><div class=l>Conciliadas</div><div class="v pos">{{ncon}}</div></div></div>
    {% if last %}<div class=card style=margin-top:16px><h3 style=margin-top:0>Importações recentes</h3>
    <table class=smart><tr><th>Arquivo</th><th data-t=date>Quando</th><th data-t=num>Conciliadas</th><th data-t=num>Novas</th></tr>
    {% for r in last %}<tr><td>{{r['filename']}}</td><td class=tag>{{r['imported_at']}}</td>
    <td>{{r['matched']}}</td><td>{{r['unmatched']}}</td></tr>{% endfor %}</table></div>{% endif %}"""
    return render(inner, last=last, nimp=nimp, ncon=ncon)


# ---------- landing page (pública) ----------
LANDING_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PIrrai — Home</title>
<style>
  :root{--bg:#0f1117;--card:#1a1d27;--border:#2a2d3a;--accent:#6c8fff;--text:#e2e4f0;--muted:#8b8fa8;--green:#4caf82;--orange:#f5a623;--red:#e05555}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;padding:0 16px 48px}
  header{text-align:center;padding:48px 0 32px}
  header h1{font-size:2rem;font-weight:700;letter-spacing:-.5px}
  header h1 span{color:var(--accent)}
  header p{color:var(--muted);margin-top:6px;font-size:.95rem}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;max-width:960px;margin:0 auto}
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px;text-decoration:none;color:inherit;display:flex;flex-direction:column;gap:10px;transition:border-color .2s,transform .15s}
  .card:hover{border-color:var(--accent);transform:translateY(-2px)}
  .card .icon{font-size:2rem;line-height:1}
  .card h2{font-size:1.1rem;font-weight:600}
  .card p{font-size:.875rem;color:var(--muted);line-height:1.5}
  .card .tag{font-size:.75rem;font-weight:600;padding:3px 8px;border-radius:20px;width:fit-content;margin-top:auto}
  .tag.green{background:rgba(76,175,130,.15);color:var(--green)}
  .tag.blue{background:rgba(108,143,255,.15);color:var(--accent)}
  .tag.orange{background:rgba(245,166,35,.15);color:var(--orange)}
  .tag.red{background:rgba(224,85,85,.15);color:var(--red)}
  .section-title{max-width:960px;margin:32px auto 12px;font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
  footer{text-align:center;margin-top:48px;color:var(--muted);font-size:.8rem}
  @media(max-width:480px){header h1{font-size:1.5rem}}
</style>
</head>
<body>
<header>
  <h1>🏠 <span>PIrrai</span></h1>
  <p>Raspberry Pi · Casa · Serviços internos</p>
</header>

<div class="section-title">Painéis</div>
<div class="grid">

  <a class="card" href="/financas" target="_self">
    <div class="icon">💰</div>
    <h2>Finanças</h2>
    <p>Transações, orçamento mensal, conciliação OFX e relatórios.</p>
    <span class="tag green">● online</span>
  </a>

  <a class="card" href="http://TAILSCALE_IP:8080" target="_blank">
    <div class="icon">🌐</div>
    <h2>Rede & Dispositivos</h2>
    <p>Inventário de dispositivos da rede local, fabricantes e status.</p>
    <span class="tag blue">LAN · porta 8080</span>
  </a>

  <a class="card" href="http://TAILSCALE_IP/admin" target="_blank">
    <div class="icon">🛡️</div>
    <h2>Pi-hole Admin</h2>
    <p>Bloqueio de anúncios e rastreadores, estatísticas de DNS e listas.</p>
    <span class="tag orange">DNS · porta 80</span>
  </a>

</div>

<div class="section-title">Em desenvolvimento</div>
<div class="grid">

  <div class="card" style="opacity:.6;cursor:default">
    <div class="icon">📓</div>
    <h2>Obsidian Vault</h2>
    <p>Busca e criação de notas do vault pessoal via sync Git.</p>
    <span class="tag orange">backlog</span>
  </div>

  <div class="card" style="opacity:.6;cursor:default">
    <div class="icon">👥</div>
    <h2>Gestão Alunos Ayty</h2>
    <p>Banco de dados e painel dos alunos dos projetos Ayty e Uaná.</p>
    <span class="tag orange">backlog</span>
  </div>

  <div class="card" style="opacity:.6;cursor:default">
    <div class="icon">📅</div>
    <h2>Google Calendar</h2>
    <p>Eventos do dia, criação de compromissos e lembretes via Telegram.</p>
    <span class="tag orange">backlog</span>
  </div>

</div>

<footer>
  pirrai · Raspberry Pi · Debian 13 · acesso via Tailscale
</footer>
</body>
</html>"""

@app.route("/transferencia", methods=["GET", "POST"])
@login_required
def transferencia():
    c = db()
    accounts = c.execute("SELECT id, name, COALESCE(currency,'BRL') currency FROM accounts ORDER BY name").fetchall()
    msg = None
    if request.method == "POST":
        f = request.form
        de_id   = int(f.get("de_id") or 0)
        para_id = int(f.get("para_id") or 0)
        val_de_str   = f.get("val_de", "").replace(",", ".")
        val_para_str = (f.get("val_para") or "").replace(",", ".")
        data    = f.get("data") or datetime.date.today().isoformat()
        desc    = f.get("desc") or "Transferência"
        if not de_id or not para_id or de_id == para_id:
            msg = ("err", "Selecione contas de origem e destino diferentes.")
        else:
            try:
                val_de_cents = int(round(float(val_de_str) * 100))
            except:
                val_de_cents = 0
            if val_de_cents <= 0:
                msg = ("err", "Valor de origem inválido.")
            else:
                # conta destino: se tiver val_para, usa; caso contrário igual ao de_id
                if val_para_str:
                    try: val_para_cents = int(round(float(val_para_str) * 100))
                    except: val_para_cents = val_de_cents
                else:
                    val_para_cents = val_de_cents

                # descobrir moedas
                acc_de   = c.execute("SELECT currency FROM accounts WHERE id=?", (de_id,)).fetchone()
                acc_para = c.execute("SELECT currency FROM accounts WHERE id=?", (para_id,)).fetchone()
                moeda_de   = (acc_de["currency"]   if acc_de   else "BRL") or "BRL"
                moeda_para = (acc_para["currency"] if acc_para else "BRL") or "BRL"

                # fx_rate (VET, taxa cheia) = origem/destino quando cross-currency
                fx_rate = None
                if moeda_de != moeda_para and val_para_str:
                    try: fx_rate = round(val_de_cents / val_para_cents, 6)
                    except: fx_rate = None

                # IOF/spread embutidos: incidem na perna em BRL de uma conversão,
                # derivados da taxa-padrão da conta global envolvida (o valor real é o bruto).
                iof_de = spread_de = iof_para = spread_para = None
                if moeda_de != moeda_para:
                    rr = c.execute("SELECT COALESCE(MAX(iof_rate),0), COALESCE(MAX(spread_rate),0) FROM accounts WHERE id IN (?,?)", (de_id, para_id)).fetchone()
                    r, s = (rr[0] or 0), (rr[1] or 0)
                    if r or s:
                        if moeda_de == "BRL":
                            comercial = val_de_cents / (1 + r + s)
                            iof_de = round(comercial * r); spread_de = round(comercial * s)
                        elif moeda_para == "BRL":
                            comercial = val_para_cents / (1 + r + s)
                            iof_para = round(comercial * r); spread_para = round(comercial * s)

                cat_transfer = "Transferência própria"
                nome_de   = next((a["name"] for a in accounts if a["id"] == de_id), str(de_id))
                nome_para = next((a["name"] for a in accounts if a["id"] == para_id), str(para_id))
                tgroup = uuid.uuid4().hex

                # débito (origem) — favorecido = conta destino
                c.execute("""INSERT INTO transactions(date,amount,amount_original,currency,fx_rate,description,category,favorecido,account_id,tx_type,source,status,transfer_group,iof_amount,spread_amount)
                             VALUES(?,?,?,?,?,?,?,?,?,'transfer','manual','confirmado',?,?,?)""",
                          (data, -val_de_cents, -val_de_cents, moeda_de, fx_rate, desc, cat_transfer, nome_para, de_id, tgroup, iof_de, spread_de))
                deb_id = c.lastrowid

                # crédito (destino) — favorecido = conta origem
                c.execute("""INSERT INTO transactions(date,amount,amount_original,currency,fx_rate,description,category,favorecido,account_id,tx_type,source,status,transfer_pair_id,transfer_group,iof_amount,spread_amount)
                             VALUES(?,?,?,?,?,?,?,?,?,'transfer','manual','confirmado',?,?,?,?)""",
                          (data, val_para_cents, val_para_cents, moeda_para, fx_rate, desc, cat_transfer, nome_de, para_id, deb_id, tgroup, iof_para, spread_para))
                cred_id = c.lastrowid

                # linkar o débito ao crédito (transfer_group já compartilhado)
                c.execute("UPDATE transactions SET transfer_pair_id=? WHERE id=?", (cred_id, deb_id))
                c.commit()

                fx_str = f" (câmbio {fx_rate:.4f})" if fx_rate else ""
                iof_str = f" · IOF R$ {(iof_de or iof_para or 0)/100:.2f}" if (iof_de or iof_para) else ""
                msg = ("ok", f"Transferência registrada: {nome_de} → {nome_para}, {moeda_de} {val_de_cents/100:.2f}{fx_str}{iof_str}")

    c.close()
    inner = """<div class=card>
    <h3 style=margin-top:0>↔ Nova Transferência entre Contas</h3>
    <p class=muted>Cria um par de transações vinculadas (débito na origem, crédito no destino). Preencha <b>Valor destino</b> apenas para câmbio.</p>
    {% if msg %}
    <div style="padding:10px 14px;border-radius:8px;margin-bottom:16px;background:{{'#3fb95033' if msg[0]=='ok' else '#f8514933'}};color:{{'var(--grn)' if msg[0]=='ok' else 'var(--red)'}}">
      {{msg[1]}}{% if msg[0]=='ok' %} — <a href="{{url_for('transacoes')}}">ver transações</a>{% endif %}
    </div>{% endif %}
    <form method=POST style="display:grid;grid-template-columns:1fr 1fr;gap:14px;max-width:560px">
      <div><label class=lbl>Conta origem</label>
        <select name=de_id required style="width:100%;padding:8px;background:var(--inbg);border:1px solid var(--ln);border-radius:8px;color:var(--ink)">
          <option value="">— selecione —</option>
          {% for a in accounts %}<option value="{{a['id']}}">{{a['name']}} ({{a['currency']}})</option>{% endfor %}
        </select></div>
      <div><label class=lbl>Conta destino</label>
        <select name=para_id required style="width:100%;padding:8px;background:var(--inbg);border:1px solid var(--ln);border-radius:8px;color:var(--ink)">
          <option value="">— selecione —</option>
          {% for a in accounts %}<option value="{{a['id']}}">{{a['name']}} ({{a['currency']}})</option>{% endfor %}
        </select></div>
      <div><label class=lbl>Valor origem</label>
        <input name=val_de type=number step=0.01 min=0.01 required placeholder="ex: 1500.00"
          style="width:100%;padding:8px;background:var(--inbg);border:1px solid var(--ln);border-radius:8px;color:var(--ink)"></div>
      <div><label class=lbl>Valor destino <span class=muted>(só para câmbio)</span></label>
        <input name=val_para type=number step=0.01 min=0 placeholder="deixe vazio se mesma moeda"
          style="width:100%;padding:8px;background:var(--inbg);border:1px solid var(--ln);border-radius:8px;color:var(--ink)"></div>
      <div><label class=lbl>Data</label>
        <input name=data type=date value="{{today}}"
          style="width:100%;padding:8px;background:var(--inbg);border:1px solid var(--ln);border-radius:8px;color:var(--ink)"></div>
      <div><label class=lbl>Descrição</label>
        <input name=desc value="Transferência"
          style="width:100%;padding:8px;background:var(--inbg);border:1px solid var(--ln);border-radius:8px;color:var(--ink)"></div>
      <div style="grid-column:1/-1">
        <button type=submit style="background:var(--acc);color:#fff;border:0;border-radius:8px;padding:10px 28px;font-size:15px;font-weight:700;cursor:pointer">Registrar transferência</button>
        <a href="{{url_for('contas')}}" style="margin-left:16px;color:var(--mut)">← Contas</a>
      </div>
    </form>
    </div>
    <style>.lbl{display:block;font-size:12px;color:var(--mut);margin-bottom:4px;font-weight:600}</style>"""
    return render(inner, accounts=accounts, msg=msg, today=datetime.date.today().isoformat())


@app.route("/investimentos")
@login_required
def investimentos():
    c = db()
    # contas de investimento (tipo contendo 'invest' ou 'previdencia', ou todas com aportes/resgates)
    inv_accounts = c.execute("""
        SELECT a.id, a.name, COALESCE(a.currency,'BRL') currency,
               COALESCE(a.opening_balance,0) opening_balance
        FROM accounts a
        WHERE LOWER(a.type) LIKE '%invest%'
           OR LOWER(a.type) LIKE '%previdên%'
           OR LOWER(a.type) LIKE '%previden%'
           OR a.id IN (SELECT DISTINCT account_id FROM transactions WHERE tx_type='rendimento' AND account_id IS NOT NULL)
        ORDER BY a.name""").fetchall()

    rows = []
    for acc in inv_accounts:
        aid = acc["id"]
        moeda = acc["currency"]
        ob = acc["opening_balance"]

        aportes   = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND amount>0 AND tx_type='transfer'", (aid,)).fetchone()[0]
        resgates  = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND amount<0 AND tx_type='transfer'", (aid,)).fetchone()[0]
        rend_pos  = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND tx_type='rendimento' AND amount>0", (aid,)).fetchone()[0]
        rend_neg  = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND tx_type='rendimento' AND amount<0", (aid,)).fetchone()[0]
        rendimento = rend_pos + rend_neg
        saldo = ob + aportes + resgates + rendimento

        # última valorização snapshot
        last_val = c.execute("SELECT value, date FROM account_valuations WHERE account_id=? ORDER BY date DESC LIMIT 1", (aid,)).fetchone()

        total_aportado = ob + aportes + resgates  # capital investido líquido
        rent_pct = (rendimento / total_aportado * 100) if total_aportado != 0 else 0.0

        rows.append({"id": aid, "name": acc["name"], "currency": moeda,
                     "aportes": aportes, "resgates": resgates,
                     "rendimento": rendimento, "saldo": saldo,
                     "rent_pct": rent_pct,
                     "last_val_value": last_val["value"] if last_val else None,
                     "last_val_date": last_val["date"] if last_val else None})
    c.close()

    inner = """<div class=card>
    <h3 style=margin-top:0>📈 Investimentos</h3>
    <p class=muted>Contas com tipo <b>investimento</b> ou com lançamentos de rendimento.
      Aportes/resgates via <a href="{{url_for('transferencia')}}">↔ Transferência</a>.
      Rendimento: use <code>finance.sh rendimento "Conta" valor</code> ou registre manualmente.</p>
    {% if not rows %}
    <p class=muted>Nenhuma conta de investimento encontrada. Crie uma conta com tipo <b>investimento</b> em <a href="{{url_for('contas')}}">Contas</a>.</p>
    {% else %}
    <table id=itbl class=smart>
    <tr><th>Conta</th><th>Moeda</th><th data-t=num>Aportes</th><th data-t=num>Resgates</th><th data-t=num>Rendimento</th><th data-t=num>Saldo</th><th data-t=num>Rentabilidade</th><th>Última valorização</th></tr>
    {% set totais_saldo = namespace(v=0) %}
    {% set totais_rend  = namespace(v=0) %}
    {% for r in rows %}
    {% set totais_saldo.v = totais_saldo.v + r.saldo %}
    {% set totais_rend.v  = totais_rend.v  + r.rendimento %}
    <tr>
      <td><b>{{r.name}}</b></td>
      <td><span class=tag>{{r.currency}}</span></td>
      <td class=num>{{'{:,.2f}'.format(r.aportes/100)}}</td>
      <td class=num style="color:var(--mut)">{{'{:,.2f}'.format(r.resgates/100)}}</td>
      <td class=num style="color:{{'var(--grn)' if r.rendimento>=0 else 'var(--red)'}}">
        {{('+' if r.rendimento>=0 else '')}}{{'{:,.2f}'.format(r.rendimento/100)}}</td>
      <td class=num><b style="color:{{'var(--grn)' if r.saldo>=0 else 'var(--red)'}}">{{'{:,.2f}'.format(r.saldo/100)}}</b></td>
      <td class=num style="color:{{'var(--grn)' if r.rent_pct>=0 else 'var(--red)'}}">
        {{('+' if r.rent_pct>=0 else '')}}{{'{:.2f}'.format(r.rent_pct)}}%</td>
      <td style="font-size:12px;color:var(--mut)">
        {% if r.last_val_value is not none %}{{'{:,.2f}'.format(r.last_val_value/100)}} em {{r.last_val_date}}
        {% else %}—{% endif %}</td>
    </tr>{% endfor %}
    <tr style="border-top:2px solid var(--ln);font-weight:700">
      <td colspan=5 style="text-align:right;color:var(--mut)">Total</td>
      <td class=num style="color:{{'var(--grn)' if totais_saldo.v>=0 else 'var(--red)'}}">{{'{:,.2f}'.format(totais_saldo.v/100)}}</td>
      <td></td><td></td>
    </tr>
    </table>
    {% endif %}
    </div>
    <style>#itbl{font-size:13px}.num{text-align:right}#itbl td,#itbl th{padding:8px 10px}</style>"""
    return render(inner, rows=rows)


@app.route("/")
def home():
    return redirect(url_for("financas"))  # raiz das Finanças vai direto pro Resumo (landing do PIrrai é a raiz do tailnet)


if __name__ == "__main__":
    # bind só em localhost; exposição segura é feita pelo `tailscale serve` (HTTPS, só no tailnet).
    app.run(host="127.0.0.1", port=8090, threaded=True)
