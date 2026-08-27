#!/usr/bin/env python3
"""Hábitos PIrrai — painel de acompanhamento (127.0.0.1:8091).

Lê o registro em SQLite (state/habitos.db) e as estratégias correntes. Escrever
continua sendo trabalho do registro.py: este processo não faz INSERT à mão.
Login pelo finance_users.json (mesma senha do painel financeiro).
"""
import datetime, functools, json, os, secrets, sys

from flask import (Flask, jsonify, redirect, render_template_string, request,
                   session, url_for)
from werkzeug.security import check_password_hash

AQUI = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(AQUI))
sys.path.insert(0, os.path.join(ROOT, "habitos"))
import registro as R          # noqa: E402
import estrategia as E        # noqa: E402

USERS_FILE = os.path.join(ROOT, "finance_users.json")
SECRET_FILE = os.path.join(AQUI, ".secret")

app = Flask(__name__)
if not os.path.exists(SECRET_FILE):
    open(SECRET_FILE, "w").write(secrets.token_hex(32))
    os.chmod(SECRET_FILE, 0o600)
app.secret_key = open(SECRET_FILE).read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=14))

QUADRANTES = {
    "ok": ("#3fb950", "no alvo"),
    "dose_insuficiente": ("#f0883e", "cumprindo, mas o objetivo não se move"),
    "nao_cabe": ("#ff7b72", "a estratégia não está cabendo"),
    "ruido": ("#8b949e", "sinal fraco"),
}


def login_required(f):
    @functools.wraps(f)
    def w(*a, **kw):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w


def users():
    try:
        return json.load(open(USERS_FILE))
    except Exception:                                        # noqa: BLE001
        return {}


def semanas(n=12):
    hoje = datetime.date.today()
    seg = hoje - datetime.timedelta(days=hoje.weekday())
    return [(seg - datetime.timedelta(weeks=i)).isoformat() for i in range(n - 1, -1, -1)]


# ── APIs ─────────────────────────────────────────────────────────────────────
@app.route("/api/resumo")
@login_required
def api_resumo():
    con = R.conectar()
    jan = semanas(12)
    out = []
    for hid in E.listar():
        try:
            spec = E.carregar(hid)
        except E.Invalida:
            continue
        sess = {r["semana"]: r["sessoes"] for r in con.execute(
            "SELECT semana, sessoes FROM v_sessoes_semanais WHERE habito=?", (hid,))}
        mets = {}
        for r in con.execute("""SELECT semana, campo, unidade, valor, agregacao, classe
                                FROM v_metricas_semanais WHERE habito=?""", (hid,)):
            mets.setdefault(r["campo"], {"unidade": r["unidade"], "agregacao": r["agregacao"],
                                         "classe": r["classe"], "valores": {}})
            mets[r["campo"]]["valores"][r["semana"]] = r["valor"]
        obst = [dict(r) for r in con.execute(
            """SELECT obstaculo, SUM(n) n FROM v_obstaculos_semanais WHERE habito=?
               GROUP BY obstaculo ORDER BY n DESC LIMIT 6""", (hid,))]
        meta = float(spec["criterio_sucesso"]["adesao"]["min"])
        atual = sess.get(jan[-1], 0)
        versoes = [dict(r) for r in con.execute(
            """SELECT versao, ativa_de, ativa_ate, autor, hipotese, desfecho
               FROM estrategias WHERE habito=? ORDER BY versao DESC""", (hid,))]
        avals = [dict(r) for r in con.execute(
            """SELECT ts, versao, adesao, resultado, quadrante, decisao, aplicada, motivo
               FROM avaliacoes WHERE habito=? ORDER BY id DESC LIMIT 10""", (hid,))]
        out.append({
            "habito": hid, "emoji": spec.get("emoji", "🎯"),
            "coach": spec.get("coach") or spec.get("nome") or hid,
            "nome": spec.get("nome") or hid, "estado": spec["estado"],
            "versao": spec["versao"], "meta": meta,
            "hipotese": spec.get("hipotese"), "motivacao": spec.get("motivacao", ""),
            "versao_minima": spec["mensagens"].get("versao_minima", ""),
            "revisar_em": spec["horizonte"].get("revisar_em"),
            "criterio_resultado": spec["criterio_sucesso"].get("resultado"),
            "gatilhos": spec.get("gatilhos", []),
            "semana_atual": {"sessoes": atual, "meta": meta},
            "serie": [{"semana": s, "sessoes": sess.get(s, 0)} for s in jan],
            "metricas": mets, "obstaculos": obst,
            "versoes": versoes, "avaliacoes": avals,
        })
    return jsonify({"habitos": out, "semanas": jan, "hoje": R.hoje()})


@app.route("/api/eventos/<habito>")
@login_required
def api_eventos(habito):
    con = R.conectar()
    rows = con.execute("""SELECT id, ts, data, tipo, origem, payload FROM eventos
                          WHERE habito=? ORDER BY data DESC, id DESC LIMIT 40""",
                       (habito,)).fetchall()
    return jsonify([{**dict(r), "payload": json.loads(r["payload"])} for r in rows])


@app.route("/api/log", methods=["POST"])
@login_required
def api_log():
    d = request.get_json(silent=True) or {}
    hid = d.get("habito")
    if not hid or hid not in E.listar():
        return jsonify({"ok": False, "err": "hábito desconhecido"}), 400
    spec = E.carregar(hid)
    con = R.conectar()
    data = d.get("data") or R.hoje()
    if d.get("fez") is False:
        R.grava_evento(con, hid, "falha", "painel", data,
                       {"obstaculo": d.get("obstaculo") or "nao_informado",
                        "nota": d.get("nota", "")})
        con.commit()
        return jsonify({"ok": True, "tipo": "falha"})
    eid = R.grava_evento(con, hid, "sessao", "painel", data, {"nota": d.get("nota", "")})
    for c in spec.get("coleta", []):
        campo = c["campo"]
        if c.get("quando") == "falha" or d.get(campo) in (None, ""):
            continue
        try:
            valor = float(d[campo])
        except (TypeError, ValueError):
            continue
        R.grava_metrica(con, hid, campo, valor, c.get("unidade"),
                        c.get("classe", "resultado" if c.get("obrigatorio") else "contexto"),
                        "painel", data, eid, agregacao=c.get("agregacao", "soma"))
    con.commit()
    return jsonify({"ok": True, "tipo": "sessao", "evento": eid})


@app.route("/api/medicao", methods=["POST"])
@login_required
def api_medicao():
    d = request.get_json(silent=True) or {}
    hid, campo = d.get("habito"), d.get("campo")
    if not hid or not campo:
        return jsonify({"ok": False, "err": "faltou hábito ou campo"}), 400
    try:
        valor = float(d.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "err": "valor inválido"}), 400
    con = R.conectar()
    # medição corporal é ponto no tempo: agregação 'ultimo', nunca somada
    R.grava_metrica(con, hid, campo, valor, d.get("unidade"), "resultado", "painel",
                    d.get("data") or R.hoje(), agregacao="ultimo")
    con.commit()
    return jsonify({"ok": True})


# ── páginas ──────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""
    if request.method == "POST":
        u = (request.form.get("user") or "").strip()
        p = request.form.get("pass") or ""
        rec = users().get(u)
        if rec and check_password_hash(rec.get("hash", ""), p):
            session.permanent = True
            session["user"] = u
            return redirect(request.args.get("next") or url_for("index"))
        erro = "usuário ou senha inválidos"
    return render_template_string(LOGIN_HTML, erro=erro)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template_string(APP_HTML, user=session.get("user", ""))


LOGIN_HTML = """<!doctype html><meta charset=utf-8><title>Hábitos</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
 body{background:#0d1117;color:#c9d1d9;font:15px/1.5 system-ui,sans-serif;
      display:grid;place-items:center;height:100vh;margin:0}
 form{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:28px;width:280px}
 h1{font-size:19px;margin:0 0 18px}
 input{width:100%;box-sizing:border-box;background:#0d1117;border:1px solid #30363d;
       color:#c9d1d9;border-radius:7px;padding:9px;margin-bottom:10px}
 button{width:100%;background:#238636;border:0;color:#fff;padding:9px;border-radius:7px;
        font-weight:600;cursor:pointer}
 .e{color:#ff7b72;font-size:13px;margin-bottom:8px}
</style>
<form method=post><h1>🎯 Hábitos</h1>
{% if erro %}<div class=e>{{erro}}</div>{% endif %}
<input name=user placeholder=usuário autofocus><input name=pass type=password placeholder=senha>
<button>entrar</button></form>"""

APP_HTML = """<!doctype html><meta charset=utf-8><title>Hábitos</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
 :root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--fg:#c9d1d9;--dim:#8b949e;--ac:#2f81f7}
 *{box-sizing:border-box}
 body{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;margin:0;
      padding:18px;max-width:1000px;margin-inline:auto}
 header{display:flex;align-items:center;gap:12px;margin-bottom:18px}
 header h1{font-size:20px;margin:0;flex:1}
 a{color:var(--ac)}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:12px;
       padding:16px 18px;margin-bottom:14px}
 .ttl{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
 .ttl h2{font-size:17px;margin:0}
 .tag{font-size:12px;color:var(--dim);border:1px solid var(--bd);border-radius:20px;
      padding:1px 9px}
 .barra{font-size:20px;letter-spacing:2px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
       margin-top:12px}
 .kpi{background:#0d1117;border:1px solid var(--bd);border-radius:9px;padding:10px 12px}
 .kpi b{display:block;font-size:21px;font-weight:600}
 .kpi span{font-size:12px;color:var(--dim)}
 svg{width:100%;height:130px;display:block;margin-top:10px}
 table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
 td,th{padding:6px 8px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:top}
 th{color:var(--dim);font-weight:500}
 .dim{color:var(--dim)}
 .q{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
 form.reg{display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-top:12px}
 form.reg label{font-size:12px;color:var(--dim);display:block}
 input,select{background:#0d1117;border:1px solid var(--bd);color:var(--fg);
              border-radius:7px;padding:7px 9px;font-size:14px}
 input[type=number]{width:92px}
 button{background:#238636;border:0;color:#fff;padding:8px 14px;border-radius:7px;
        font-weight:600;cursor:pointer}
 button.sec{background:#21262d;border:1px solid var(--bd);color:var(--fg)}
 details summary{cursor:pointer;color:var(--dim);font-size:13px;margin-top:10px}
 .ok{color:#3fb950}.warn{color:#f0883e}.bad{color:#ff7b72}
</style>
<header><h1>🎯 Hábitos</h1><span class=dim>{{user}}</span> <a href=/logout>sair</a></header>
<div id=app class=dim>carregando…</div>
<script>
const QCOR = {ok:"#3fb950", dose_insuficiente:"#f0883e", nao_cabe:"#ff7b72", ruido:"#8b949e"};
let ST = null;

function barra(n, meta){
  const cheias = Math.min(n, meta);
  return "🟢".repeat(cheias) + "⚪".repeat(Math.max(0, meta - cheias)) +
         (n > meta ? "🟢".repeat(n - meta) : "");
}
function grafico(serie, metricas, meta){
  const w = 720, h = 130, pad = 18, n = serie.length;
  const larg = (w - pad*2) / n;
  const maxS = Math.max(meta, ...serie.map(s => s.sessoes), 1);
  let barras = serie.map((s, i) => {
    const alt = (s.sessoes / maxS) * (h - 38);
    const x = pad + i*larg, y = h - 20 - alt;
    const cor = s.sessoes >= meta ? "#3fb950" : (s.sessoes ? "#f0883e" : "#21262d");
    return `<rect x=${x+3} y=${y} width=${larg-6} height=${Math.max(alt,2)} rx=3 fill="${cor}"/>` +
           `<text x=${x+larg/2} y=${h-6} fill="#8b949e" font-size=9 text-anchor=middle>` +
           `${s.semana.slice(8,10)}/${s.semana.slice(5,7)}</text>`;
  }).join("");
  const ymeta = h - 20 - (meta/maxS)*(h-38);
  barras += `<line x1=${pad} y1=${ymeta} x2=${w-pad} y2=${ymeta} stroke="#2f81f7" ` +
            `stroke-dasharray="4 4" stroke-width=1/>`;
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${barras}</svg>`;
}
function metricasHTML(m){
  const linhas = Object.entries(m).map(([campo, d]) => {
    const vals = Object.entries(d.valores).sort();
    if(!vals.length) return "";
    const ult = vals[vals.length-1];
    const rot = d.agregacao === "ultimo" ? "última medição" : "última semana";
    return `<div class=kpi><b>${(+ult[1]).toFixed(campo==="vo2max"?1:0)}${d.unidade?" "+d.unidade:""}</b>
            <span>${campo} · ${rot} (${ult[0].slice(8,10)}/${ult[0].slice(5,7)})</span></div>`;
  }).join("");
  return linhas ? `<div class=grid>${linhas}</div>` : "";
}
function coachHTML(h){
  if(!h.avaliacoes.length && h.versoes.length < 2)
    return `<div class=dim style="margin-top:10px">Sem revisão registrada ainda.
            Próxima: <b>${h.revisar_em || "não marcada"}</b>.</div>`;
  const av = h.avaliacoes.map(a => {
    const [cor, txt] = [QCOR[a.quadrante] || "#8b949e", a.quadrante || "—"];
    return `<tr><td class=dim>${a.ts.slice(0,10)}</td>
      <td><span class=q style="background:${cor}"></span>${txt}</td>
      <td>${a.decisao || "—"} ${a.aplicada ? "" : "<span class=dim>(não aplicada)</span>"}</td>
      <td class=dim>adesão ${a.adesao === null ? "—" : (a.adesao*100).toFixed(0)+"%"}</td>
      <td class=dim>${(a.motivo||"").slice(0,90)}</td></tr>`;
  }).join("");
  const vs = h.versoes.map(v => `<tr><td>v${v.versao}</td><td class=dim>${v.ativa_de} →
      ${v.ativa_ate || "agora"}</td><td class=dim>${v.autor||""}</td>
      <td class=dim>${v.desfecho || ""}</td><td class=dim>${(v.hipotese||"").slice(0,80)}</td></tr>`).join("");
  return `<details open><summary>revisões do coach</summary>
     <table><tr><th>quando</th><th>quadrante</th><th>decisão</th><th></th><th>motivo</th></tr>
     ${av}</table></details>
     <details><summary>versões da estratégia</summary>
     <table><tr><th>v</th><th>no ar</th><th>autor</th><th>desfecho</th><th>hipótese</th></tr>
     ${vs}</table></details>`;
}
function formHTML(h){
  const campos = (h.gatilhos, ["minutos","fc_media"]).map(c =>
    `<div><label>${c}</label><input type=number step=any id="f-${h.habito}-${c}"></div>`).join("");
  return `<form class=reg onsubmit="return registrar('${h.habito}')">
    <div><label>data</label><input type=date id="f-${h.habito}-data" value="${ST.hoje}"></div>
    ${campos}
    <div style="flex:1;min-width:160px"><label>nota</label>
      <input style="width:100%" id="f-${h.habito}-nota" placeholder="bike interna, puxado no fim"></div>
    <button>registrar treino</button>
    <button type=button class=sec onclick="naoFiz('${h.habito}')">não fiz</button>
  </form>`;
}
function render(){
  document.getElementById("app").className = "";
  document.getElementById("app").innerHTML = ST.habitos.map(h => {
    const at = h.semana_atual;
    const prox = h.revisar_em ? `revisão em ${h.revisar_em}` : "sem revisão marcada";
    const dose = Object.entries(h.metricas).filter(([,d]) => d.agregacao === "soma");
    return `<div class=card>
      <div class=ttl><h2>${h.emoji} Coach: ${h.coach}</h2>
        <span class=tag>${h.estado}</span><span class=tag>estratégia v${h.versao}</span>
        <span class=tag>${prox}</span></div>
      <div class=barra style="margin-top:8px">${barra(at.sessoes, at.meta)}
        <span class=dim style="font-size:14px">${at.sessoes}/${at.meta} esta semana</span></div>
      ${h.hipotese ? `<div class=dim style="margin-top:6px">hipótese: ${h.hipotese}</div>` : ""}
      ${h.versao_minima ? `<div class=dim style="margin-top:4px">mínimo: ${h.versao_minima}</div>` : ""}
      ${grafico(h.serie, h.metricas, h.meta)}
      ${metricasHTML(h.metricas)}
      ${h.obstaculos.length ? `<div class=dim style="margin-top:10px">obstáculos: ` +
        h.obstaculos.map(o => `${o.obstaculo} ×${o.n}`).join(" · ") + `</div>` : ""}
      ${formHTML(h)}
      ${coachHTML(h)}
    </div>`;
  }).join("") || "<div class=card>Nenhuma estratégia encontrada.</div>";
}
async function registrar(hid){
  const g = c => document.getElementById(`f-${hid}-${c}`).value;
  const body = {habito:hid, data:g("data"), nota:g("nota"),
                minutos:g("minutos"), fc_media:g("fc_media")};
  await fetch("/api/log", {method:"POST", headers:{"Content-Type":"application/json"},
                           body:JSON.stringify(body)});
  carregar(); return false;
}
async function naoFiz(hid){
  const o = prompt("o que atrapalhou? (agenda, cansaco, esqueci, ambiente, doenca, viagem, sem_vontade)");
  if(o === null) return;
  await fetch("/api/log", {method:"POST", headers:{"Content-Type":"application/json"},
    body:JSON.stringify({habito:hid, fez:false, obstaculo:o,
                         data:document.getElementById(`f-${hid}-data`).value})});
  carregar();
}
async function carregar(){ ST = await (await fetch("/api/resumo")).json(); render(); }
carregar();
</script>"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8091, debug=False)
