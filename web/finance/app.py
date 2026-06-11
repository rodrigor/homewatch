#!/usr/bin/env python3
"""Finanças PIrrai — web app (F1 base): login, dashboard, listagem e lançamento manual.
Bind em 127.0.0.1:8090 (dados financeiros NÃO ficam expostos na LAN; acesso via VPN/SSH-tunnel)."""
import os, json, sqlite3, subprocess, secrets, datetime, functools
from flask import (Flask, request, session, redirect, url_for,
                   render_template_string, flash, abort)
from werkzeug.security import check_password_hash

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../homewatch
DB = os.path.join(ROOT, "finance.db")
USERS = os.path.join(ROOT, "finance_users.json")
FINANCE_SH = os.path.join(ROOT, "finance.sh")
SECRET = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret")

app = Flask(__name__)
if not os.path.exists(SECRET):
    with open(SECRET, "w") as fh: fh.write(secrets.token_hex(32))
    os.chmod(SECRET, 0o600)
app.secret_key = open(SECRET).read().strip()

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

def login_required(f):
    @functools.wraps(f)
    def w(*a, **k):
        if "user" not in session: return redirect(url_for("login", next=request.path))
        return f(*a, **k)
    return w

app.jinja_env.filters["brl"] = brl

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
<a href="{{url_for('nova')}}">+ Lançar</a><a href="{{url_for('senha')}}">Senha</a>
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
    c = db()
    rows = c.execute("""SELECT t.*, a.name acc FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
                        WHERE substr(t.date,1,7)=? ORDER BY t.date DESC, t.id DESC""", (mes,)).fetchall()
    c.close()
    inner = """<div class=card><div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
    <h3 style="margin:0;flex:1">Transações · {{mes}}</h3>
    <form><input type=month name=mes value="{{mes}}" onchange=this.form.submit()></form>
    <a class=btn href="{{url_for('nova')}}">+ Lançar</a></div>
    {% if rows %}<table><tr><th>Data</th><th>Descrição</th><th>Categoria</th><th>Conta</th><th>Status</th><th style=text-align:right>Valor</th></tr>
    {% for r in rows %}<tr><td>{{r['date']}}</td><td>{{r['description'] or '—'}}</td>
    <td class=tag>{{r['category'] or '—'}}</td><td class=tag>{{r['acc'] or '—'}}</td><td class=tag>{{r['status']}}</td>
    <td style=text-align:right class="{{'pos' if r['amount']>0 else 'neg'}}">{{r['amount']|brl}}</td></tr>{% endfor %}</table>
    {% else %}<p class=muted>Nada em {{mes}}.</p>{% endif %}</div>"""
    return render(inner, mes=mes, rows=rows)

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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8090, threaded=True)
