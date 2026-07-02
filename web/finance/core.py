#!/usr/bin/env python3
"""Finanças PIrrai — núcleo: app factory, banco, helpers, filtros, CSRF e execução em background.
Bind em 127.0.0.1:8090 (dados financeiros NÃO ficam expostos na LAN; acesso via VPN/SSH-tunnel)."""
import os, sys, json, sqlite3, subprocess, secrets, datetime, functools, threading, logging
from flask import Flask, request, session, redirect, url_for, abort

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../homewatch
sys.path.insert(0, ROOT)
DB = os.environ.get("FINANCE_DB", os.path.join(ROOT, "finance.db"))
USERS = os.path.join(ROOT, "finance_users.json")
FINANCE_SH = os.path.join(ROOT, "finance.sh")
SECRET = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret")
log = logging.getLogger("finance")

# ---------- banco / usuários ----------
def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def users():
    try:
        with open(USERS) as fh: return json.load(fh)
    except Exception: return {}

# ---------- formatação ----------
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

def parse_cents(s):  # "-67,90" / "R$ 1.234,56" -> centavos (preserva sinal; '.' é milhar)
    s = (s or "").replace("R$", "").replace(" ", "").strip()
    neg = s.startswith("-"); s = s.lstrip("+-").replace(".", "").replace(",", ".")
    try: c = int(round(float(s) * 100))
    except Exception: return None
    return -c if neg else c

# ---------- constantes de domínio ----------
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
TITULARES = ["Ayla", "Rodrigo", "Casa"]  # dono da conta (atribui as despesas a uma pessoa)

# ---------- auth / CSRF ----------
def login_required(f):
    @functools.wraps(f)
    def w(*a, **k):
        if "user" not in session: return redirect(url_for("auth.login", next=request.path))
        return f(*a, **k)
    return w

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]

# ---------- background ----------
def run_bg(*cmds, timeout=600):
    """roda comandos em sequência numa thread — não bloqueia a resposta HTTP."""
    def _run():
        for cmd in cmds:
            try:
                subprocess.run(cmd, capture_output=True, timeout=timeout)
            except Exception:
                log.exception("run_bg falhou: %s", cmd)
    threading.Thread(target=_run, daemon=True).start()

# ---------- app factory ----------
def create_app():
    app = Flask(__name__)
    if not os.path.exists(SECRET):
        with open(SECRET, "w") as fh: fh.write(secrets.token_hex(32))
        os.chmod(SECRET, 0o600)
    app.secret_key = open(SECRET).read().strip()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=7))
    app.jinja_env.filters["brl"] = brl
    app.jinja_env.filters["reais_plain"] = reais_plain
    app.jinja_env.filters["money"] = money
    app.jinja_env.globals["cursym"] = cursym
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def _csrf_protect():
        if request.method == "POST":
            tok = session.get("_csrf", "")
            sent = request.headers.get("X-CSRF") or request.form.get("_csrf", "")
            if not tok or not sent or not secrets.compare_digest(tok, sent):
                if request.path.startswith("/api/"):
                    return {"ok": False, "err": "sessão expirada — recarregue a página"}, 403
                abort(403)

    import migrations
    con = db()
    migrations.migrate(con)
    con.close()

    import bp_auth, bp_dashboard, bp_transacoes, bp_favorecidos, bp_contas, bp_regras
    for m in (bp_auth, bp_dashboard, bp_transacoes, bp_favorecidos, bp_contas, bp_regras):
        app.register_blueprint(m.bp)
    return app
