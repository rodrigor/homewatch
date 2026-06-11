#!/usr/bin/env python3
"""Finanças PIrrai — web app (F1 base): login, dashboard, listagem e lançamento manual.
Bind em 127.0.0.1:8090 (dados financeiros NÃO ficam expostos na LAN; acesso via VPN/SSH-tunnel)."""
import os, sys, json, sqlite3, subprocess, secrets, datetime, functools
from flask import (Flask, request, session, redirect, url_for,
                   render_template_string, flash, abort)
from werkzeug.security import check_password_hash

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../homewatch
sys.path.insert(0, ROOT)
import ofx_parser
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

def parse_cents(s):  # "-67,90" / "R$ 1.234,56" / "45.90" -> centavos (preserva sinal)
    s = (s or "").replace("R$", "").replace(" ", "").strip()
    neg = s.startswith("-"); s = s.lstrip("+-").replace(".", "").replace(",", ".")
    try: c = int(round(float(s) * 100))
    except Exception: return None
    return -c if neg else c

STATUSES = ["pendente", "confirmado", "conciliado", "importado", "agendado"]

def login_required(f):
    @functools.wraps(f)
    def w(*a, **k):
        if "user" not in session: return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w

app.jinja_env.filters["brl"] = brl
app.jinja_env.filters["reais_plain"] = reais_plain

# ---------- templates ----------
BASE = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Finanças · PIrrai</title><style>
:root{--bg:#0f1419;--card:#1a2230;--ink:#e6edf3;--mut:#8b98a9;--ln:#263041;--acc:#2f81f7;--red:#f85149;--grn:#3fb950}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:var(--acc);text-decoration:none}.wrap{max-width:980px;margin:0 auto;padding:18px}
header{display:flex;align-items:center;gap:16px;border-bottom:1px solid var(--ln);padding:14px 18px;background:var(--card)}
header b{font-size:18px}header nav{display:flex;gap:14px;margin-left:auto;align-items:center}
.card{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.kpi .v{font-size:24px;font-weight:700}.kpi .l{color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--ln)}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.neg{color:var(--red)}.pos{color:var(--grn)}.tag{font-size:12px;color:var(--mut)}
input,select,button{font:inherit;padding:9px 11px;border-radius:9px;border:1px solid var(--ln);background:#0d1117;color:var(--ink)}
button,.btn{background:var(--acc);border:0;color:#fff;cursor:pointer;font-weight:600;padding:9px 16px}
.flash{background:#1f6feb22;border:1px solid var(--acc);padding:10px 14px;border-radius:9px;margin-bottom:14px}
form.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}label{display:block;font-size:13px;color:var(--mut);margin-bottom:4px}
.full{grid-column:1/-1}.muted{color:var(--mut)}
</style></head><body>
{% if session.user %}<header><b>💰 Finanças</b>
<nav><a href="{{url_for('dashboard')}}">Resumo</a><a href="{{url_for('transacoes')}}">Transações</a>
<a href="{{url_for('nova')}}">+ Lançar</a><a href="{{url_for('conciliacao')}}">Conciliar</a><a href="{{url_for('senha')}}">Senha</a>
<span class=muted>{{session.user}}</span><a href="{{url_for('logout')}}">sair</a></nav></header>{% endif %}
<div class=wrap>
{% with m=get_flashed_messages() %}{% if m %}<div class=flash>{{m|join(' · ')}}</div>{% endif %}{% endwith %}
{% block body %}{% endblock %}</div></body></html>"""

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
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Usuário ou senha inválidos.")
    inner = """<div class=card style="max-width:360px;margin:8vh auto">
    <h2 style="margin-top:0">💰 Finanças · PIrrai</h2>
    <form method=post><label>Usuário</label><input name=user autofocus style=width:100%>
    <label style=margin-top:10px>Senha</label><input name=pw type=password style=width:100%>
    <button style="margin-top:16px;width:100%">Entrar</button></form></div>"""
    return render(inner)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

# ---------- dashboard ----------
@app.route("/")
@login_required
def dashboard():
    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    c = db()
    desp = c.execute("SELECT COALESCE(-SUM(amount),0) FROM transactions WHERE amount<0 AND substr(date,1,7)=?", (mes,)).fetchone()[0]
    rec  = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE amount>0 AND substr(date,1,7)=?", (mes,)).fetchone()[0]
    n    = c.execute("SELECT COUNT(*) FROM transactions WHERE substr(date,1,7)=?", (mes,)).fetchone()[0]
    pend = c.execute("SELECT COUNT(*) FROM transactions WHERE status='pendente'").fetchone()[0]
    cats = c.execute("""SELECT COALESCE(category,'—') cat, -SUM(amount) v FROM transactions
                        WHERE amount<0 AND substr(date,1,7)=? GROUP BY category ORDER BY v DESC""", (mes,)).fetchall()
    c.close()
    inner = """<div class=grid>
    <div class="card kpi"><div class=l>Despesas ({{mes}})</div><div class="v neg">{{desp|brl}}</div></div>
    <div class="card kpi"><div class=l>Receitas</div><div class="v pos">{{rec|brl}}</div></div>
    <div class="card kpi"><div class=l>Saldo</div><div class="v">{{(rec-desp)|brl}}</div></div>
    <div class="card kpi"><div class=l>Transações</div><div class=v>{{n}}</div><div class=tag>{{pend}} pendente(s)</div></div></div>
    <div class=card><h3 style=margin-top:0>Por categoria</h3>
    {% if cats %}<table><tr><th>Categoria</th><th style=text-align:right>Gasto</th></tr>
    {% for r in cats %}<tr><td>{{r['cat']}}</td><td style=text-align:right class=neg>{{r['v']|brl}}</td></tr>{% endfor %}</table>
    {% else %}<p class=muted>Sem lançamentos em {{mes}}. <a href="{{url_for('nova')}}">Lançar o primeiro →</a></p>{% endif %}</div>"""
    return render(inner, mes=mes, desp=desp, rec=rec, n=n, pend=pend, cats=cats)

# ---------- listagem ----------
@app.route("/transacoes")
@login_required
def transacoes():
    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    f_conta = request.args.get("conta", ""); f_cat = request.args.get("categoria", "")
    f_status = request.args.get("status", ""); q = request.args.get("q", "").strip()
    where = ["substr(t.date,1,7)=?"]; params = [mes]
    if f_conta:  where.append("t.account_id=?"); params.append(f_conta)
    if f_cat:    where.append("COALESCE(t.category,'')=?"); params.append(f_cat)
    if f_status: where.append("t.status=?"); params.append(f_status)
    if q:        where.append("(t.description LIKE ? OR t.merchant LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    c = db()
    rows = c.execute(f"""SELECT t.*, a.name acc FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
                        WHERE {' AND '.join(where)} ORDER BY t.date DESC, t.id DESC""", params).fetchall()
    accs = c.execute("SELECT id,name FROM accounts ORDER BY name").fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY name").fetchall()
    tot = sum(r["amount"] for r in rows); c.close()
    inner = """<div class=card><div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
    <h3 style="margin:0;flex:1">Transações</h3><a class=btn href="{{url_for('nova')}}">+ Lançar</a></div>
    <form class=filtros>
      <input type=month name=mes value="{{mes}}" onchange=this.form.submit()>
      <select name=conta onchange=this.form.submit()><option value="">Conta: todas</option>
        {% for a in accs %}<option value="{{a['id']}}" {{'selected' if f_conta==a['id']|string}}>{{a['name']}}</option>{% endfor %}</select>
      <select name=categoria onchange=this.form.submit()><option value="">Categoria: todas</option>
        {% for ct in cats %}<option {{'selected' if f_cat==ct['name']}}>{{ct['name']}}</option>{% endfor %}</select>
      <select name=status onchange=this.form.submit()><option value="">Status: todos</option>
        {% for s in statuses %}<option {{'selected' if f_status==s}}>{{s}}</option>{% endfor %}</select>
      <input name=q value="{{q}}" placeholder="buscar…" onkeydown="if(event.key=='Enter')this.form.submit()">
      {% if f_conta or f_cat or f_status or q %}<a href="{{url_for('transacoes',mes=mes)}}" class=muted>limpar</a>{% endif %}
    </form>
    {% if rows %}<table id=tx><tr><th>Data</th><th>Descrição</th><th>Categoria</th><th>Conta</th><th>Status</th><th style=text-align:right>Valor (R$)</th><th></th></tr>
    {% for r in rows %}<tr class="st-{{r['status']}}">
      <td><input type=date value="{{r['date'] or ''}}" onchange="sv({{r['id']}},'date',this)"></td>
      <td><input value="{{r['description'] or ''}}" onchange="sv({{r['id']}},'description',this)" style=min-width:160px></td>
      <td><select onchange="sv({{r['id']}},'category',this)"><option value="">—</option>
        {% for ct in cats %}<option {{'selected' if r['category']==ct['name']}}>{{ct['name']}}</option>{% endfor %}</select></td>
      <td><select onchange="sv({{r['id']}},'account_id',this)"><option value="">—</option>
        {% for a in accs %}<option value="{{a['id']}}" {{'selected' if r['account_id']==a['id']}}>{{a['name']}}</option>{% endfor %}</select></td>
      <td><select onchange="sv({{r['id']}},'status',this)">
        {% for s in statuses %}<option {{'selected' if r['status']==s}}>{{s}}</option>{% endfor %}</select></td>
      <td style=text-align:right><input class="val {{'pos' if r['amount']>0 else 'neg'}}" value="{{r['amount']|reais_plain}}"
        onchange="sv({{r['id']}},'amount',this)" style="width:92px;text-align:right"></td>
      <td><button class=del title=excluir onclick="dl({{r['id']}})">✕</button></td></tr>{% endfor %}
    <tr><td colspan=5 style=text-align:right class=muted>Total filtrado</td>
      <td style=text-align:right class="{{'pos' if tot>0 else 'neg'}}"><b>{{tot|brl}}</b></td><td></td></tr></table>
    {% else %}<p class=muted>Nada encontrado. <a href="{{url_for('nova')}}">Lançar →</a></p>{% endif %}</div>
    <style>.filtros{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.filtros>*{font-size:13px}
    #tx input,#tx select{background:transparent;border:1px solid transparent;border-radius:6px;color:var(--ink);padding:5px 6px;width:100%}
    #tx input:hover,#tx select:hover{border-color:var(--ln)}#tx input:focus,#tx select:focus{border-color:var(--acc);background:#0d1117;outline:none}
    #tx .val.neg{color:var(--red)}#tx .val.pos{color:var(--grn)}.saved{background:#3fb95033!important}.err{border-color:var(--red)!important}
    button.del{background:transparent;color:var(--mut);padding:4px 8px;font-size:14px}button.del:hover{color:var(--red)}
    tr.st-pendente{background:#f0883e0e}tr.st-conciliado td{box-shadow:none}tr.st-conciliado{background:#3fb9500a}tr.st-importado{background:#f8514910}</style>
    <script>
    function sv(id,field,el){const b='field='+field+'&value='+encodeURIComponent(el.value);
      fetch('/api/tx/'+id,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:b})
      .then(r=>r.json()).then(j=>{el.classList.remove('err','saved');el.classList.add(j.ok?'saved':'err');
        if(j.ok&&field=='status'){el.closest('tr').className='st-'+el.value;}
        setTimeout(()=>el.classList.remove('saved'),700);}).catch(()=>el.classList.add('err'));}
    function dl(id){if(!confirm('Excluir esta transação?'))return;
      fetch('/api/tx/'+id+'/delete',{method:'POST'}).then(()=>location.reload());}
    </script>"""
    return render(inner, mes=mes, rows=rows, accs=accs, cats=cats, statuses=STATUSES,
                  f_conta=f_conta, f_cat=f_cat, f_status=f_status, q=q, tot=tot)

@app.route("/api/tx/<int:tid>", methods=["POST"])
@login_required
def api_tx(tid):
    field = request.form.get("field"); value = request.form.get("value", "")
    if field not in {"date", "description", "merchant", "category", "status", "account_id", "amount"}:
        return {"ok": False, "err": "campo inválido"}, 400
    c = db()
    if field == "amount":
        cents = parse_cents(value)
        if cents is None: c.close(); return {"ok": False, "err": "valor inválido"}, 400
        c.execute("UPDATE transactions SET amount=? WHERE id=?", (cents, tid))
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
    c = db(); c.execute("DELETE FROM transactions WHERE id=?", (tid,)); c.commit(); c.close()
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

@app.route("/conciliacao", methods=["GET", "POST"])
@login_required
def conciliacao():
    c = db()
    if request.method == "POST":
        f = request.files.get("ofx")
        if not f or not f.filename:
            flash("Selecione um arquivo OFX."); c.close(); return redirect(url_for("conciliacao"))
        txns = ofx_parser.parse(f.read().decode("latin-1", "replace"))
        matched = imported = dup = 0
        for t in txns:
            if t["fitid"] and c.execute("SELECT 1 FROM transactions WHERE external_id=?", (t["fitid"],)).fetchone():
                dup += 1; continue
            cand = c.execute(
                """SELECT id FROM transactions WHERE amount=? AND source<>'ofx' AND external_id IS NULL
                   AND ABS(julianday(date)-julianday(?))<=2
                   ORDER BY ABS(julianday(date)-julianday(?)) LIMIT 1""",
                (t["cents"], t["date"], t["date"])).fetchone()
            if cand:
                c.execute("UPDATE transactions SET status='conciliado', external_id=? WHERE id=?",
                          (t["fitid"], cand["id"])); matched += 1
            else:
                c.execute("""INSERT INTO transactions(date,amount,description,source,status,external_id)
                             VALUES(?,?,?,'ofx','importado',?)""",
                          (t["date"], t["cents"], t["memo"], t["fitid"])); imported += 1
        c.execute("INSERT INTO ofx_imports(filename,matched,unmatched) VALUES(?,?,?)",
                  (f.filename, matched, imported)); c.commit()
        flash(f"OFX “{f.filename}”: {len(txns)} lidas · {matched} conciliadas · {imported} novas · {dup} já existentes")
        c.close(); return redirect(url_for("conciliacao"))
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
    <table><tr><th>Arquivo</th><th>Quando</th><th>Conciliadas</th><th>Novas</th></tr>
    {% for r in last %}<tr><td>{{r['filename']}}</td><td class=tag>{{r['imported_at']}}</td>
    <td>{{r['matched']}}</td><td>{{r['unmatched']}}</td></tr>{% endfor %}</table></div>{% endif %}"""
    return render(inner, last=last, nimp=nimp, ncon=ncon)


if __name__ == "__main__":
    # bind só em localhost; exposição segura é feita pelo `tailscale serve` (HTTPS, só no tailnet).
    app.run(host="127.0.0.1", port=8090, threaded=True)
