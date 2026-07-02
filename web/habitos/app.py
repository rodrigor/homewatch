#!/usr/bin/env python3
"""Hábitos PIrrai — dashboard de acompanhamento pessoal.
Porta 8091. Login via finance_users.json (mesma senha do financeiro).
"""
import os, sys, json, secrets, datetime, glob, functools, calendar
from flask import (Flask, request, session, redirect, url_for,
                   render_template_string, jsonify)
from werkzeug.security import check_password_hash

ROOT        = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HABITS_DIR  = os.path.join(ROOT, "habits")
USERS_FILE  = os.path.join(ROOT, "finance_users.json")
SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret")

app = Flask(__name__)
if not os.path.exists(SECRET_FILE):
    with open(SECRET_FILE, "w") as f: f.write(secrets.token_hex(32))
    os.chmod(SECRET_FILE, 0o600)
app.secret_key = open(SECRET_FILE).read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=14))

HABIT_COLORS = ["#2f81f7", "#3fb950", "#f0883e", "#bc8cff", "#ff7b72", "#58a6ff"]

# ── helpers ───────────────────────────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def w(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w

def load_users():
    try:
        with open(USERS_FILE) as f: return json.load(f)
    except: return {}

def monday_of(d):
    return d - datetime.timedelta(days=d.weekday())

def load_habits(person):
    files = sorted(glob.glob(os.path.join(HABITS_DIR, person, "*.json")))
    out = []
    for fp in files:
        if os.path.basename(fp) == "perfil.json": continue
        try:
            with open(fp) as f: h = json.load(f)
            h["_file"] = fp
            if h.get("status") == "active": out.append(h)
        except: pass
    return out

def load_perfil(person):
    fp = os.path.join(HABITS_DIR, person, "perfil.json")
    try:
        with open(fp) as f: return json.load(f)
    except: return {"medicoes": [], "metas": {}}

def save_json(fp, data):
    tmp = fp + ".tmp"
    with open(tmp, "w") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fp)

def plan_phase(habit):
    """(week_num, phase_name, phase_desc) baseado em semanas desde criação."""
    start = datetime.date.fromtimestamp(habit.get("created", 0))
    weeks = max(1, (datetime.date.today() - start).days // 7 + 1)
    if weeks <= 4:
        return weeks, "Fase 1 — Base Zona 2", "25-35 min ergométrica · 106-123 bpm"
    elif weeks <= 8:
        return weeks, "Fase 2 — Progressão", "2× Zona 2 (40 min) + 1× HIIT 30s/90s × 8"
    else:
        return weeks, "Fase 3 — Intensidade", "1× Zona 2 longo (50 min) + 2× HIIT"

# ── auth ──────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    err = ""
    if request.method == "POST":
        u = request.form.get("user", "").strip()
        p = request.form.get("pass", "")
        us = load_users()
        if u in us and check_password_hash(us[u]["hash"], p):
            session.permanent = True
            session["user"] = u
            return redirect(request.args.get("next") or url_for("index"))
        err = "Usuário ou senha incorretos."
    return render_template_string(LOGIN_HTML, err=err)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

# ── SPA ───────────────────────────────────────────────────────────────────
@app.route("/")
@app.route("/habitos")
@login_required
def index():
    return render_template_string(MAIN_HTML, user=session.get("user", ""))

# ── API: status semana atual ───────────────────────────────────────────────
@app.route("/api/status")
@login_required
def api_status():
    person = "Rodrigo"
    habits = load_habits(person)
    perfil = load_perfil(person)
    today  = datetime.date.today()
    mon    = monday_of(today).isoformat()

    result = []
    for i, h in enumerate(habits):
        logs     = h.get("log", [])
        done_wk  = sum(1 for e in logs if e.get("done") and (e.get("date") or "") >= mon)
        target   = h.get("target_per_week", 1)
        last     = next((e for e in reversed(logs) if e.get("done")), None)
        wk_logs  = [e for e in logs if e.get("done") and (e.get("date") or "") >= mon]
        metrics  = {}
        for e in wk_logs:
            if e.get("value") and e.get("unit"):
                u = e["unit"]; metrics[u] = metrics.get(u, 0) + (e["value"] or 0)
        is_ex    = "exerc" in h.get("name", "").lower()
        wn, pname, pdesc = plan_phase(h) if is_ex else (0, "", "")
        result.append({
            "id": h["id"], "name": h["name"], "type": h.get("type"),
            "target": target, "done_this_week": done_wk,
            "streak": h.get("streak_weeks", 0),
            "color": HABIT_COLORS[i % len(HABIT_COLORS)],
            "last_log": last, "week_metrics": metrics,
            "why": h.get("why", ""), "tiny": h.get("tiny", ""),
            "week_num": wn, "phase_name": pname, "phase_desc": pdesc,
        })

    meds    = perfil.get("medicoes", [])
    last_m  = meds[-1] if meds else {}
    metas   = perfil.get("metas", {})
    return jsonify({
        "habits": result,
        "perfil": {
            "peso": last_m.get("peso_kg"), "vo2": last_m.get("vo2max"),
            "imc": last_m.get("imc"),
            "peso_alvo": metas.get("peso_alvo_kg"), "vo2_alvo": metas.get("vo2max_alvo"),
            "zona2": metas.get("zona2_bpm"), "zona4": metas.get("zona4_bpm"),
            "fc_max": metas.get("fc_max_bpm"),
        },
        "today": today.isoformat(), "week_start": mon,
    })

# ── API: calendário ───────────────────────────────────────────────────────
@app.route("/api/calendar/<int:year>/<int:month>")
@login_required
def api_calendar(year, month):
    person = "Rodrigo"
    habits = load_habits(person)
    colors = {h["id"]: HABIT_COLORS[i % len(HABIT_COLORS)] for i, h in enumerate(habits)}
    names  = {h["id"]: h["name"] for h in habits}

    day_map = {}
    prefix  = f"{year:04d}-{month:02d}"
    for h in habits:
        for e in h.get("log", []):
            d = e.get("date", "")
            if not d.startswith(prefix): continue
            day_map.setdefault(d, []).append({
                "hid": h["id"], "name": names[h["id"]],
                "color": colors[h["id"]], "done": e.get("done", False),
                "value": e.get("value"), "unit": e.get("unit", ""), "note": e.get("note", ""),
            })

    MN = ["","Janeiro","Fevereiro","Março","Abril","Maio","Junho",
          "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    # Monday-first calendar
    cal = calendar.monthcalendar(year, month)
    return jsonify({"grid": cal, "days": day_map, "year": year,
                    "month": month, "month_name": MN[month],
                    "habits": [{"id": h["id"], "name": h["name"],
                                "color": HABIT_COLORS[i % len(HABIT_COLORS)]}
                               for i, h in enumerate(habits)]})

# ── API: histórico ────────────────────────────────────────────────────────
@app.route("/api/historico")
@login_required
def api_historico():
    person  = "Rodrigo"
    habits  = load_habits(person)
    hfilter = request.args.get("habit")
    entries = []
    for i, h in enumerate(habits):
        if hfilter and h["id"] != hfilter: continue
        color = HABIT_COLORS[i % len(HABIT_COLORS)]
        for e in h.get("log", []):
            entries.append({"date": e.get("date"), "habit_id": h["id"],
                            "habit_name": h["name"], "color": color,
                            "done": e.get("done", False), "value": e.get("value"),
                            "unit": e.get("unit", ""), "note": e.get("note", "")})
    entries.sort(key=lambda x: x["date"] or "", reverse=True)
    return jsonify({"entries": entries[:120],
                    "habits": [{"id": h["id"], "name": h["name"]} for h in habits]})

# ── API: métricas ─────────────────────────────────────────────────────────
@app.route("/api/metricas")
@login_required
def api_metricas():
    person = "Rodrigo"
    habits = load_habits(person)
    perfil = load_perfil(person)
    meds   = sorted(perfil.get("medicoes", []), key=lambda x: x.get("data", ""))

    ex = next((h for h in habits if "exerc" in h.get("name", "").lower()), None)
    semanas = []
    if ex:
        today = datetime.date.today()
        for i in range(11, -1, -1):
            ws = monday_of(today - datetime.timedelta(weeks=i))
            we = ws + datetime.timedelta(days=6)
            ws_s, we_s = ws.isoformat(), we.isoformat()
            mins = sum((e.get("value") or 0) for e in ex.get("log", [])
                       if e.get("done") and e.get("unit", "") == "min"
                       and ws_s <= (e.get("date") or "") <= we_s)
            sess = sum(1 for e in ex.get("log", [])
                       if e.get("done") and ws_s <= (e.get("date") or "") <= we_s)
            semanas.append({"week": ws.strftime("%d/%m"), "minutes": mins, "sessions": sess})

    return jsonify({"medicoes": meds, "semanas": semanas,
                    "metas": perfil.get("metas", {}),
                    "altura_cm": perfil.get("altura_cm", 178)})

# ── API: salvar log ───────────────────────────────────────────────────────
@app.route("/api/log", methods=["POST"])
@login_required
def api_log():
    person = "Rodrigo"
    data   = request.get_json(silent=True) or {}
    hid    = data.get("habit_id")
    date_s = data.get("date") or datetime.date.today().isoformat()
    done   = data.get("done", True)
    val    = data.get("value")
    unit   = data.get("unit", "")
    note   = data.get("note", "")

    fp = os.path.join(HABITS_DIR, person, f"{hid}.json")
    if not os.path.exists(fp): return jsonify({"ok": False, "err": "hábito não encontrado"}), 404
    with open(fp) as f: habit = json.load(f)

    try: val = float(val) if val not in (None, "") else None
    except: val = None

    habit["log"] = [e for e in habit.get("log", []) if e.get("date") != date_s]
    habit["log"].append({"date": date_s, "done": done, "value": val, "unit": unit, "note": note})
    habit["log"].sort(key=lambda x: x.get("date", ""))
    save_json(fp, habit)
    return jsonify({"ok": True})

# ── API: nova medição de perfil ───────────────────────────────────────────
@app.route("/api/perfil/medicao", methods=["POST"])
@login_required
def api_medicao():
    person = "Rodrigo"
    data   = request.get_json(silent=True) or {}
    fp     = os.path.join(HABITS_DIR, person, "perfil.json")
    try:
        with open(fp) as f: perfil = json.load(f)
    except: return jsonify({"ok": False, "err": "perfil não encontrado"}), 404

    date_s = data.get("data") or datetime.date.today().isoformat()
    peso   = float(data["peso_kg"])  if data.get("peso_kg")  else None
    vo2    = float(data["vo2max"])   if data.get("vo2max")   else None
    altura = (perfil.get("altura_cm", 178)) / 100
    imc    = round(peso / altura**2, 1) if peso else None
    vo2abs = round(vo2 * peso / 1000, 2) if (vo2 and peso) else None

    med = {"data": date_s}
    if peso:   med["peso_kg"] = peso
    if vo2:    med["vo2max"]  = vo2
    if imc:    med["imc"]     = imc
    if vo2abs: med["vo2_absoluto_lmin"] = vo2abs

    perfil["medicoes"] = [m for m in perfil.get("medicoes", []) if m.get("data") != date_s]
    perfil["medicoes"].append(med)
    perfil["medicoes"].sort(key=lambda x: x.get("data", ""))
    save_json(fp, perfil)
    return jsonify({"ok": True, "imc": imc})

# ── HTML: login ───────────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html><html lang=pt-BR>
<head><meta charset=UTF-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Hábitos — PIrrai</title>
<style>*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:32px 36px;width:340px}
h2{font-size:20px;margin-bottom:4px}.sub{color:#8b949e;font-size:13px;margin-bottom:24px}
label{display:block;font-size:12px;color:#8b949e;margin-bottom:5px;font-weight:600}
input{width:100%;padding:9px 12px;background:#0d1117;border:1px solid #30363d;border-radius:8px;
  color:#e6edf3;font-size:14px;margin-bottom:16px}
input:focus{outline:none;border-color:#2f81f7}
button{width:100%;padding:10px;background:#2f81f7;color:#fff;border:0;border-radius:8px;
  font-size:15px;font-weight:700;cursor:pointer}button:hover{background:#388bfd}
.err{color:#f85149;font-size:13px;margin-bottom:12px}
</style></head>
<body><div class=box>
<h2>🏃 Hábitos</h2><p class=sub>PIrrai · painel pessoal</p>
{% if err %}<div class=err>{{err}}</div>{% endif %}
<form method=POST>
  <label>Usuário</label><input name=user autocomplete=username>
  <label>Senha</label><input name=pass type=password autocomplete=current-password>
  <button type=submit>Entrar</button>
</form></div></body></html>"""

# ── HTML: SPA principal ───────────────────────────────────────────────────
MAIN_HTML = """<!DOCTYPE html><html lang=pt-BR>
<head><meta charset=UTF-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Hábitos — PIrrai</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--mut:#8b949e;--acc:#2f81f7;
  --grn:#3fb950;--red:#f85149;--ln:#30363d;--inbg:#0d1117;--ora:#f0883e}
body{background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh}
a{color:var(--acc);text-decoration:none}
/* header */
header{background:var(--card);border-bottom:1px solid var(--ln);padding:0 20px;
  display:flex;align-items:center;gap:12px;height:52px;position:sticky;top:0;z-index:100}
header b{font-size:17px}
nav{display:flex;gap:3px;margin-left:auto}
.tab{padding:6px 14px;border-radius:20px;font-size:13px;font-weight:600;cursor:pointer;
  color:var(--mut);background:transparent;border:0;transition:all .15s}
.tab:hover{color:var(--ink);background:#ffffff12}.tab.on{color:#fff;background:var(--acc)}
.usr{color:var(--mut);font-size:12px;margin-left:8px}
/* layout */
main{max-width:980px;margin:0 auto;padding:20px 16px}
/* cards */
.card{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:20px;margin-bottom:16px}
.card h3{font-size:14px;font-weight:700;margin-bottom:14px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:620px){.g2,.g3{grid-template-columns:1fr}}
/* phase banner */
.phase{background:linear-gradient(135deg,#2f81f71a,#3fb9500a);border:1px solid #2f81f730;
  border-radius:12px;padding:14px 18px;margin-bottom:16px;position:relative;overflow:hidden}
.phase-wk{position:absolute;right:16px;top:10px;font-size:48px;font-weight:900;
  color:#2f81f715;line-height:1}
.phase-tag{font-size:10px;color:var(--acc);font-weight:700;text-transform:uppercase;letter-spacing:.6px}
.phase-name{font-size:17px;font-weight:800;color:var(--ink);margin:3px 0}
.phase-desc{font-size:13px;color:var(--mut)}
/* KPI */
.kpi{text-align:center;padding:18px 12px}
.kpi-v{font-size:30px;font-weight:800;line-height:1}
.kpi-l{font-size:11px;color:var(--mut);margin-top:4px;font-weight:600;text-transform:uppercase;letter-spacing:.4px}
.kpi-s{font-size:11px;color:var(--mut);margin-top:3px}
.bar{height:5px;background:var(--ln);border-radius:3px;margin-top:10px}
.bar-f{height:100%;border-radius:3px;transition:width .6s}
/* habit cards */
.hcard{background:var(--card);border:1px solid var(--ln);border-radius:12px;padding:18px 18px 14px}
.hcard-name{font-size:15px;font-weight:800;margin-bottom:3px}
.hcard-why{font-size:11px;color:var(--mut);margin-bottom:12px;line-height:1.5}
.dots{display:flex;gap:7px;margin:10px 0 6px}
.dot{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:11px;font-weight:700}
.dot.hit{color:#fff}.dot.mis{background:var(--ln);color:#30363d}
.pbar{height:5px;background:var(--ln);border-radius:3px;margin-bottom:8px}
.pbar-f{height:100%;border-radius:3px;transition:width .5s}
.htxt{font-size:12px;color:var(--mut)}
.streak{font-size:12px;color:var(--mut);margin-top:4px}
.streak b{color:var(--ora)}
.mpill{font-size:11px;background:#21262d;border-radius:10px;padding:3px 9px;
  color:var(--ink);display:inline-block;margin-top:5px}
.last{font-size:11px;color:var(--mut);margin-top:5px}
.logbtn{width:100%;margin-top:12px;padding:7px;border:1px dashed var(--ln);background:transparent;
  border-radius:8px;color:var(--mut);cursor:pointer;font-size:12px;transition:all .15s}
.logbtn:hover{border-color:var(--acc);color:var(--acc);background:#2f81f708}
/* zones */
.zcard{border-radius:10px;padding:12px 16px}
.z2{background:#2f81f710;border:1px solid #2f81f730}
.z4{background:#f0883e10;border:1px solid #f0883e30}
.ztag{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
.zbpm{font-size:24px;font-weight:800;line-height:1}
.zdesc{font-size:11px;color:var(--mut);margin-top:4px}
/* sections */
.sec{display:none}.sec.on{display:block}
/* calendar */
.cal-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.cal-nav{background:transparent;border:1px solid var(--ln);border-radius:6px;color:var(--ink);
  padding:4px 14px;cursor:pointer;font-size:16px}.cal-nav:hover{border-color:var(--acc)}
.cgrid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
.cdow{text-align:center;font-size:10px;font-weight:700;color:var(--mut);padding:6px 0;text-transform:uppercase}
.cday{min-height:58px;border:1px solid var(--ln);border-radius:7px;padding:5px;cursor:default}
.cday.today{border-color:var(--acc)!important}
.cday.empty{background:transparent;border-color:transparent}
.cday-n{font-size:11px;color:var(--mut);font-weight:600}
.cday.today .cday-n{color:var(--acc);font-weight:800}
.cdots{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.cdot{width:8px;height:8px;border-radius:50%}
.cdot.miss{background:var(--ln)}
/* histórico */
.htbl{width:100%;border-collapse:collapse;font-size:13px}
.htbl th{text-align:left;color:var(--mut);font-weight:600;font-size:10px;text-transform:uppercase;
  letter-spacing:.4px;padding:7px 10px;border-bottom:1px solid var(--ln)}
.htbl td{padding:8px 10px;border-bottom:1px solid #21262d}
.htbl tr:last-child td{border:0}
.bdg{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
/* charts */
.chwrap{position:relative;height:190px;margin-top:8px}
/* modal */
.overlay{position:fixed;inset:0;background:#000a;z-index:200;display:flex;
  align-items:center;justify-content:center}.overlay.hidden{display:none}
.modal{background:var(--card);border:1px solid var(--ln);border-radius:14px;
  padding:26px;width:360px;max-width:92vw}
.modal h3{margin-bottom:16px;font-size:16px}
.fr{margin-bottom:13px}
.fr label{display:block;font-size:11px;color:var(--mut);font-weight:700;
  text-transform:uppercase;letter-spacing:.4px;margin-bottom:5px}
.fr input,.fr select{width:100%;padding:8px 11px;background:var(--inbg);border:1px solid var(--ln);
  border-radius:8px;color:var(--ink);font-size:14px}
.fr input:focus,.fr select:focus{outline:none;border-color:var(--acc)}
.mact{display:flex;gap:10px;margin-top:16px}
.btn{padding:8px 18px;border-radius:8px;border:0;cursor:pointer;font-size:13px;font-weight:700}
.btn-p{background:var(--acc);color:#fff}.btn-p:hover{background:#388bfd}
.btn-c{background:transparent;border:1px solid var(--ln);color:var(--mut)}
.btn-c:hover{border-color:var(--red);color:var(--red)}
.muted{color:var(--mut);font-size:13px}
</style></head>
<body>
<header>
  <b>🏃 Hábitos</b>
  <nav>
    <button class="tab on" onclick="goTab('dashboard',this)">Dashboard</button>
    <button class="tab"    onclick="goTab('calendario',this)">Calendário</button>
    <button class="tab"    onclick="goTab('historico',this)">Histórico</button>
    <button class="tab"    onclick="goTab('metricas',this)">Métricas</button>
  </nav>
  <span class=usr>{{user}} · <a href="/logout">sair</a></span>
</header>
<main>

<!-- DASHBOARD -->
<div id=dashboard class="sec on">
  <div id=phase></div>
  <div id=kpis class=g3 style="margin-bottom:16px"></div>
  <div id=hgrid class=g2></div>
  <div id=zones class=g2 style="margin-top:14px"></div>
</div>

<!-- CALENDÁRIO -->
<div id=calendario class=sec>
  <div class=card>
    <div class=cal-hdr>
      <button class=cal-nav onclick="calNav(-1)">‹</button>
      <span id=cal-title style="font-weight:700;font-size:16px"></span>
      <button class=cal-nav onclick="calNav(+1)">›</button>
    </div>
    <div class=cgrid>
      <div class=cdow>Seg</div><div class=cdow>Ter</div><div class=cdow>Qua</div>
      <div class=cdow>Qui</div><div class=cdow>Sex</div><div class=cdow>Sáb</div>
      <div class=cdow>Dom</div>
    </div>
    <div class=cgrid id=cal-grid style="margin-top:3px"></div>
    <div id=cal-leg style="display:flex;gap:14px;margin-top:14px;flex-wrap:wrap"></div>
  </div>
</div>

<!-- HISTÓRICO -->
<div id=historico class=sec>
  <div class=card>
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
      <h3 style="margin:0">Histórico</h3>
      <select id=hfilt onchange="loadHist()"
        style="background:var(--inbg);border:1px solid var(--ln);border-radius:7px;color:var(--ink);padding:5px 10px;font-size:13px">
        <option value="">Todos</option>
      </select>
    </div>
    <div id=hist-body></div>
  </div>
</div>

<!-- MÉTRICAS -->
<div id=metricas class=sec>
  <div class=g2 style="margin-bottom:14px">
    <div class=card><h3>VO2 Max</h3><div class=chwrap><canvas id=c-vo2></canvas></div></div>
    <div class=card><h3>Peso (kg)</h3><div class=chwrap><canvas id=c-peso></canvas></div></div>
  </div>
  <div class=card style="margin-bottom:14px">
    <h3>Minutos de exercício por semana</h3>
    <div class=chwrap style="height:170px"><canvas id=c-min></canvas></div>
  </div>
  <div class=card>
    <h3>Registrar medição</h3>
    <div class=g2 style="margin-bottom:14px">
      <div class=fr><label>Data</label><input type=date id=med-dt></div>
      <div></div>
      <div class=fr><label>Peso (kg)</label><input type=number step=0.1 id=med-p placeholder=87.5></div>
      <div class=fr><label>VO2 Max</label><input type=number step=0.1 id=med-v placeholder=30.5></div>
    </div>
    <button class="btn btn-p" onclick="saveMed()">Salvar medição</button>
    <span id=med-msg style="margin-left:12px;font-size:13px"></span>
  </div>
</div>

</main>

<!-- Modal de log -->
<div class="overlay hidden" id=modal onclick="closeModal(event)">
<div class=modal onclick="event.stopPropagation()">
  <h3 id=m-title>Registrar</h3>
  <input type=hidden id=m-hid>
  <div class=fr><label>Data</label><input type=date id=m-date></div>
  <div class=fr><label>Feito?</label>
    <select id=m-done>
      <option value=true>✅ Sim, fiz!</option>
      <option value=false>❌ Não fiz (registrar falta)</option>
    </select>
  </div>
  <div class=fr><label>Quanto? (número)</label>
    <input type=number step=0.1 id=m-val placeholder="ex: 35"></div>
  <div class=fr><label>Unidade</label>
    <input id=m-unit placeholder="min / km / sessão"></div>
  <div class=fr><label>Nota</label>
    <input id=m-note placeholder="ex: bike zona 2, musculação..."></div>
  <div class=mact>
    <button class="btn btn-p" onclick="submitLog()">Salvar</button>
    <button class="btn btn-c" onclick="closeModal()">Cancelar</button>
  </div>
</div>
</div>

<script>
let ST = null, CHARTS = {}, calY, calM, histOk = false;

// ── tabs ──────────────────────────────────────────────────────────────────
function goTab(id, btn) {
  document.querySelectorAll('.sec').forEach(s => s.classList.remove('on'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  btn.classList.add('on');
  if (id === 'calendario' && !calY) { const n=new Date(); calY=n.getFullYear(); calM=n.getMonth()+1; loadCal(); }
  if (id === 'historico') loadHist();
  if (id === 'metricas')  loadMetricas();
}

// ── dashboard ─────────────────────────────────────────────────────────────
async function loadDashboard() {
  const r = await fetch('/api/status'); ST = await r.json();
  renderPhase(); renderKPIs(); renderHabits(); renderZones();
}

function renderPhase() {
  const ex = ST.habits.find(h => h.week_num > 0);
  if (!ex) { document.getElementById('phase').innerHTML=''; return; }
  document.getElementById('phase').innerHTML =
    `<div class=phase><div class=phase-wk>S${ex.week_num}</div>
     <div class=phase-tag>Semana ${ex.week_num} do plano VO2</div>
     <div class=phase-name>${ex.phase_name}</div>
     <div class=phase-desc>${ex.phase_desc}</div></div>`;
}

function renderKPIs() {
  const p = ST.perfil;
  const done = ST.habits.reduce((s,h)=>s+h.done_this_week,0);
  const tgt  = ST.habits.reduce((s,h)=>s+h.target,0);
  const vo2p  = p.vo2_alvo ? Math.min(100,Math.round(((p.vo2||0)/(p.vo2_alvo))*100)) : 0;
  const peso0 = 87.5, pesoA = p.peso_alvo||82;
  const pesop = p.peso ? Math.min(100,Math.max(0,Math.round(((peso0-(p.peso))/(peso0-pesoA))*100))) : 0;
  const actp  = tgt ? Math.round(done/tgt*100) : 0;
  document.getElementById('kpis').innerHTML = `
    <div class="card kpi">
      <div class=kpi-v style="color:#2f81f7">${p.vo2||'—'}</div>
      <div class=kpi-l>VO2 Max</div>
      <div class=kpi-s>meta ${p.vo2_alvo||40} · ${vo2p}% do caminho</div>
      <div class=bar><div class=bar-f style="width:${vo2p}%;background:#2f81f7"></div></div>
    </div>
    <div class="card kpi">
      <div class=kpi-v style="color:#3fb950">${p.peso?p.peso.toFixed(1):'—'}</div>
      <div class=kpi-l>Peso kg · IMC ${p.imc||'—'}</div>
      <div class=kpi-s>meta ${pesoA} kg · ${pesop}% do caminho</div>
      <div class=bar><div class=bar-f style="width:${pesop}%;background:#3fb950"></div></div>
    </div>
    <div class="card kpi">
      <div class=kpi-v style="color:#f0883e">${done}<span style="font-size:16px;font-weight:400">/${tgt}</span></div>
      <div class=kpi-l>Hábitos esta semana</div>
      <div class=kpi-s>${new Date().toLocaleDateString('pt-BR',{weekday:'long'})}</div>
      <div class=bar><div class=bar-f style="width:${actp}%;background:#f0883e"></div></div>
    </div>`;
}

function renderHabits() {
  document.getElementById('hgrid').innerHTML = ST.habits.map(h => {
    const pct   = Math.round(h.done_this_week/h.target*100);
    const dots  = Array.from({length:h.target},(_,i)=>
      `<div class="dot ${i<h.done_this_week?'hit':'mis'}"
        style="${i<h.done_this_week?'background:'+h.color:''}">${i<h.done_this_week?'✓':''}</div>`).join('');
    const strk  = h.streak>0 ? `<div class=streak>🔥 Streak: <b>${h.streak} semana${h.streak>1?'s':''}</b></div>` : '';
    const met   = Object.entries(h.week_metrics||{}).map(([u,v])=>
      `<span class=mpill>📈 ${Math.round(v)} ${u} esta semana</span>`).join('');
    const last  = h.last_log
      ? `<div class=last>↩ ${h.last_log.date}${h.last_log.value?' · '+h.last_log.value+' '+(h.last_log.unit||''):''}${h.last_log.note?' · '+h.last_log.note:''}</div>` : '';
    const tiny  = h.tiny ? `<div class=last style="margin-top:4px;color:#58a6ff">💡 ${h.tiny}</div>` : '';
    return `<div class=hcard>
      <div class=hcard-name style="color:${h.color}">${h.name}</div>
      <div class=hcard-why>${h.why||''}</div>
      <div class=dots>${dots}</div>
      <div class=pbar><div class=pbar-f style="width:${pct}%;background:${h.color}"></div></div>
      <div class=htxt>${h.done_this_week}/${h.target} ${h.type==='daily'?'dias esta semana':'vezes esta semana'}</div>
      ${strk}${met}${last}${tiny}
      <button class=logbtn onclick="openModal('${h.id}','${h.name}')">＋ Registrar</button>
    </div>`;
  }).join('');
}

function renderZones() {
  const p = ST.perfil;
  document.getElementById('zones').innerHTML = `
    <div class="zcard z2">
      <div class=ztag style="color:#2f81f7">🫀 Zona 2 — Base aeróbica</div>
      <div class=zbpm style="color:#2f81f7">${p.zona2||'106–123'} <span style="font-size:14px;font-weight:400">bpm</span></div>
      <div class=zdesc>Conversa fluida · ergométrica/bike · Fase 1 (sem 1-4)</div>
    </div>
    <div class="zcard z4">
      <div class=ztag style="color:#f0883e">⚡ Zona 4 — HIIT (sem 5+)</div>
      <div class=zbpm style="color:#f0883e">${p.zona4||'141–158'} <span style="font-size:14px;font-weight:400">bpm</span></div>
      <div class=zdesc>30s esforço máximo / 90s leve · 8 rounds</div>
    </div>`;
}

// ── calendário ─────────────────────────────────────────────────────────────
async function loadCal() {
  const r = await fetch(`/api/calendar/${calY}/${calM}`); const d = await r.json();
  document.getElementById('cal-title').textContent = `${d.month_name} ${d.year}`;
  document.getElementById('cal-leg').innerHTML = d.habits.map(h=>
    `<span style="display:flex;align-items:center;gap:5px;font-size:12px;color:var(--mut)">
      <span style="width:10px;height:10px;border-radius:50%;background:${h.color};display:inline-block"></span>${h.name}</span>`
  ).join('');
  const today = new Date().toISOString().slice(0,10);
  document.getElementById('cal-grid').innerHTML = d.grid.map(wk=>wk.map(day=>{
    if(!day) return '<div class="cday empty"></div>';
    const ds = `${d.year}-${String(d.month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    const isT = ds===today;
    const dd  = d.days[ds]||[];
    const dots = d.habits.map(h=>{
      const e = dd.find(x=>x.hid===h.id);
      if(!e) return '';
      return `<div class="cdot ${e.done?'':'miss'}"
        style="${e.done?'background:'+h.color:''}"
        title="${h.name}${e.note?' — '+e.note:''}${e.value?' · '+e.value+(e.unit||''):''}"></div>`;
    }).join('');
    return `<div class="cday${isT?' today':''}">
      <div class=cday-n>${day}</div><div class=cdots>${dots}</div></div>`;
  }).join('')).join('');
}
function calNav(d){ calM+=d; if(calM>12){calM=1;calY++;} if(calM<1){calM=12;calY--;} loadCal(); }

// ── histórico ──────────────────────────────────────────────────────────────
async function loadHist() {
  const f = document.getElementById('hfilt').value;
  const r = await fetch('/api/historico'+(f?`?habit=${f}`:'')); const d = await r.json();
  if(!histOk){
    histOk=true;
    d.habits.forEach(h=>{ const o=document.createElement('option');o.value=h.id;o.textContent=h.name;
      document.getElementById('hfilt').appendChild(o);});
    if(f) document.getElementById('hfilt').value=f;
  }
  const rows = d.entries.map(e=>`<tr>
    <td>${e.date}</td>
    <td><span class=bdg style="background:${e.color}"></span>${e.habit_name}</td>
    <td>${e.done?'✅':'❌'}</td>
    <td>${e.value!=null?e.value+' '+(e.unit||''):'—'}</td>
    <td style="color:var(--mut)">${e.note||'—'}</td></tr>`).join('')
    || '<tr><td colspan=5 style="text-align:center;padding:24px;color:var(--mut)">Nenhum registro ainda</td></tr>';
  document.getElementById('hist-body').innerHTML=
    `<table class=htbl><tr><th>Data</th><th>Hábito</th><th>Feito</th><th>Métrica</th><th>Nota</th></tr>${rows}</table>`;
}

// ── métricas ───────────────────────────────────────────────────────────────
async function loadMetricas() {
  const r = await fetch('/api/metricas'); const d = await r.json();
  document.getElementById('med-dt').value = new Date().toISOString().slice(0,10);
  const co = { responsive:true, maintainAspectRatio:false,
    plugins:{legend:{display:false}},
    scales:{x:{ticks:{color:'#8b949e',font:{size:10}},grid:{color:'#21262d'}},
            y:{ticks:{color:'#8b949e',font:{size:10}},grid:{color:'#21262d'}}}};
  const meds = d.medicoes;
  if(CHARTS.vo2) CHARTS.vo2.destroy();
  CHARTS.vo2 = new Chart(document.getElementById('c-vo2'),{type:'line',
    data:{labels:meds.map(m=>m.data),
      datasets:[{data:meds.map(m=>m.vo2max),borderColor:'#2f81f7',
        backgroundColor:'#2f81f720',tension:.3,fill:true,pointRadius:5,pointHoverRadius:7}]},
    options:{...co}});
  if(CHARTS.peso) CHARTS.peso.destroy();
  CHARTS.peso = new Chart(document.getElementById('c-peso'),{type:'line',
    data:{labels:meds.map(m=>m.data),
      datasets:[{data:meds.map(m=>m.peso_kg),borderColor:'#3fb950',
        backgroundColor:'#3fb95020',tension:.3,fill:true,pointRadius:5,pointHoverRadius:7}]},
    options:{...co}});
  if(CHARTS.min) CHARTS.min.destroy();
  CHARTS.min = new Chart(document.getElementById('c-min'),{type:'bar',
    data:{labels:d.semanas.map(s=>s.week),
      datasets:[{data:d.semanas.map(s=>s.minutes),
        backgroundColor:d.semanas.map(s=>s.sessions>=3?'#3fb95080':'#2f81f780'),
        borderRadius:4}]},
    options:{...co}});
}

async function saveMed() {
  const p={data:document.getElementById('med-dt').value,
    peso_kg:parseFloat(document.getElementById('med-p').value)||null,
    vo2max:parseFloat(document.getElementById('med-v').value)||null};
  const r=await fetch('/api/perfil/medicao',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  const d=await r.json();
  const el=document.getElementById('med-msg');
  if(d.ok){el.style.color='var(--grn)';el.textContent=`✅ Salvo! IMC: ${d.imc}`;
    loadMetricas();loadDashboard();}
  else{el.style.color='var(--red)';el.textContent=d.err||'Erro';}
  setTimeout(()=>el.textContent='',3000);
}

// ── modal ──────────────────────────────────────────────────────────────────
function openModal(hid,name){
  document.getElementById('m-title').textContent='Registrar: '+name;
  document.getElementById('m-hid').value=hid;
  document.getElementById('m-date').value=new Date().toISOString().slice(0,10);
  document.getElementById('m-done').value='true';
  document.getElementById('m-val').value='';
  document.getElementById('m-unit').value='min';
  document.getElementById('m-note').value='';
  document.getElementById('modal').classList.remove('hidden');
}
function closeModal(e){
  if(!e||e.target===document.getElementById('modal'))
    document.getElementById('modal').classList.add('hidden');
}
async function submitLog(){
  const p={habit_id:document.getElementById('m-hid').value,
    date:document.getElementById('m-date').value,
    done:document.getElementById('m-done').value==='true',
    value:parseFloat(document.getElementById('m-val').value)||null,
    unit:document.getElementById('m-unit').value,
    note:document.getElementById('m-note').value};
  const r=await fetch('/api/log',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});
  const d=await r.json();
  if(d.ok){closeModal();loadDashboard();}
  else alert(d.err||'Erro ao salvar');
}

// ── init ────────────────────────────────────────────────────────────────────
loadDashboard();
</script></body></html>"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8091, debug=False)
