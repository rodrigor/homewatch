#!/usr/bin/env python3
"""PIrrai — página inicial com links para os serviços no ar. Bind 127.0.0.1:8087 (exposto via tailscale serve na raiz)."""
from flask import Flask, Response

app = Flask(__name__)
HOST = "pirrai.tail414b9b.ts.net"

# (icone, nome, descrição, url, cor)
SERVICES = [
    ("💰", "Finanças", "Controle financeiro — gastos, receitas, favorecidos", f"https://{HOST}:8443", "#3fb950"),
    ("🌐", "Pi-hole", "Bloqueio de anúncios e painel de DNS da casa", f"http://{HOST}/admin", "#c62828"),
    ("🖥️", "Dispositivos", "Inventário da rede — quem está conectado", f"http://{HOST}:8080", "#2f81f7"),
    ("📶", "Omada", "Controlador da rede Wi-Fi (TP-Link)", f"http://{HOST}:8088", "#00838f"),
]

PAGE = """<!doctype html><html lang=pt-br><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>PIrrai</title><style>
:root{{--bg:#0f1419;--card:#1a2230;--ink:#e6edf3;--mut:#8b98a9;--ln:#263041}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;font:16px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
background:radial-gradient(1200px 600px at 50% -10%,#1a2230 0,var(--bg) 60%);color:var(--ink);
display:flex;flex-direction:column;align-items:center;padding:48px 18px}}
h1{{font-size:30px;margin:0 0 2px;letter-spacing:-.5px}}h1 .em{{font-size:34px}}
.sub{{color:var(--mut);margin:0 0 36px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;width:100%;max-width:760px}}
a.card{{display:flex;gap:14px;align-items:center;text-decoration:none;color:var(--ink);
background:var(--card);border:1px solid var(--ln);border-radius:14px;padding:18px 18px;
transition:transform .12s,border-color .12s}}
a.card:hover{{transform:translateY(-3px);border-color:var(--ac)}}
.ico{{font-size:30px;width:48px;height:48px;display:flex;align-items:center;justify-content:center;
border-radius:12px;background:#0d1117;flex:0 0 auto;box-shadow:inset 0 0 0 1px var(--ln)}}
.nm{{font-weight:700;font-size:17px}}.ds{{color:var(--mut);font-size:13px;margin-top:2px}}
footer{{color:var(--mut);font-size:12px;margin-top:40px}}
</style></head><body>
<h1><span class=em>🤖</span> PIrrai</h1>
<p class=sub>Serviços da casa — Raspberry Pi</p>
<div class=grid>{cards}</div>
<footer>{host}</footer></body></html>"""

CARD = """<a class=card href="{url}" style="--ac:{cor}">
  <div class=ico>{ico}</div><div><div class=nm>{nome}</div><div class=ds>{desc}</div></div></a>"""


@app.route("/")
def home():
    cards = "".join(CARD.format(ico=i, nome=n, desc=d, url=u, cor=c) for i, n, d, u, c in SERVICES)
    return Response(PAGE.format(cards=cards, host=HOST), mimetype="text/html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8087, threaded=True)
