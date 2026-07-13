#!/usr/bin/env python3
"""finance_report.py — relatório financeiro mensal por e-mail (HTML).
Reusa as mesmas regras do dashboard (movimentações excluídas, nível efetivo por lançamento).
Uso:
  finance_report.py                -> mês anterior (uso via timer no dia 1)
  finance_report.py --mes 2026-06  -> mês específico
  finance_report.py --dry          -> só renderiza pro stdout/arquivo, NÃO envia
"""
import os, sys, ssl, smtplib, sqlite3, datetime
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "finance.db")

def load_env(path):
    if not os.path.exists(path): return
    for ln in open(path):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env(os.path.join(ROOT, "email.env"))
load_env(os.path.join(ROOT, "config.env"))

NOTRANSFER = "COALESCE(category,'') NOT IN (SELECT name FROM categories WHERE is_transfer=1)"
NIVEFF = "COALESCE(t.nivel, cat.nivel, t.email_hint_nivel, 0)"
MESN = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

def brl(c):
    s = f"{abs(c)/100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if c < 0 else "") + "R$ " + s

def prev_month(d):
    y, m = d.year, d.month - 1
    if m == 0: m = 12; y -= 1
    return f"{y:04d}-{m:02d}"

def mes_label(mes):
    return f"{MESN[int(mes[5:7])-1]}/{mes[:4]}"

def compute(con, mes):
    q = con.execute
    g1 = lambda sql, p=(): (q(sql, p).fetchone() or [0])[0] or 0
    desp = g1(f"SELECT -SUM(amount) FROM transactions WHERE amount<0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=0", (mes,))
    exc  = g1(f"SELECT -SUM(amount) FROM transactions WHERE amount<0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=1", (mes,))
    rec  = g1(f"SELECT SUM(amount) FROM transactions WHERE amount>0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=0", (mes,))
    n    = g1("SELECT COUNT(*) FROM transactions WHERE substr(date,1,7)=?", (mes,))
    semcat = g1(f"SELECT COUNT(*) FROM transactions WHERE substr(date,1,7)=? AND (category IS NULL OR category='') AND amount<0", (mes,))
    grupos = q("""SELECT COALESCE(c.grupo,'(sem grupo)') g, -SUM(t.amount) v
                  FROM transactions t LEFT JOIN categories c ON c.name=t.category
                  WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(c.is_transfer,0)=0 AND COALESCE(t.excepcional,0)=0
                  GROUP BY c.grupo ORDER BY v DESC""", (mes,)).fetchall()
    cats = q(f"""SELECT COALESCE(NULLIF(t.category,''),'(sem categoria)') cat, -SUM(t.amount) v
                 FROM transactions t LEFT JOIN categories cat ON cat.name=t.category
                 WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(cat.is_transfer,0)=0 AND COALESCE(t.excepcional,0)=0
                 GROUP BY t.category ORDER BY v DESC LIMIT 10""", (mes,)).fetchall()
    niv = {r[0]: r[1] for r in q(f"""SELECT {NIVEFF} niv, -SUM(t.amount) v
                 FROM transactions t LEFT JOIN categories cat ON cat.name=t.category
                 WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(cat.is_transfer,0)=0 AND COALESCE(t.excepcional,0)=0
                 GROUP BY {NIVEFF}""", (mes,)).fetchall()}
    pessoa = {}
    for r in q(f"""SELECT COALESCE(a.titular,'(sem titular)') p, {NIVEFF} niv, -SUM(t.amount) v
                 FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id LEFT JOIN categories cat ON cat.name=t.category
                 WHERE t.amount<0 AND substr(t.date,1,7)=? AND COALESCE(cat.is_transfer,0)=0
                 GROUP BY a.titular, {NIVEFF}""", (mes,)).fetchall():
        pessoa.setdefault(r[0], {0:0,1:0,2:0,3:0})[r[1]] = r[2]
    orc = q("""SELECT b.category cat, b.limit_amount lim,
                 COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=b.category AND amount<0 AND substr(date,1,7)=?),0) spent
                 FROM budgets b WHERE b.month='*' AND b.limit_amount>0 ORDER BY (spent*1.0/b.limit_amount) DESC""", (mes,)).fetchall()
    desp_prev = g1(f"SELECT -SUM(amount) FROM transactions WHERE amount<0 AND substr(date,1,7)=? AND {NOTRANSFER} AND COALESCE(excepcional,0)=0", (prev_month(datetime.date(int(mes[:4]), int(mes[5:7]), 1)),))
    return dict(desp=desp, exc=exc, rec=rec, n=n, semcat=semcat, grupos=grupos, cats=cats,
                niv=niv, pessoa=pessoa, orc=orc, desp_prev=desp_prev)

def bar(pct, color):
    pct = max(0, min(100, pct))
    return (f'<div style="background:#eef1f5;border-radius:5px;height:9px;overflow:hidden">'
            f'<div style="width:{pct:.0f}%;height:100%;background:{color};border-radius:5px"></div></div>')

def render_html(mes, d):
    NC = {1:"#2f81f7", 2:"#3fb950", 3:"#ef6c00", 0:"#6e7681"}
    NL = {1:"N1 Comprometido", 2:"N2 Necessário", 3:"N3 Discricionário", 0:"Sem nível"}
    saldo = d["rec"] - d["desp"]
    delta = d["desp"] - d["desp_prev"]
    dtxt = ""
    if d["desp_prev"]:
        pc = delta * 100 / d["desp_prev"]
        dtxt = f' <span style="color:{"#d1242f" if delta>0 else "#1a7f37"};font-size:13px">({"+" if delta>0 else ""}{pc:.0f}% vs mês anterior)</span>'
    maxg = max([r[1] for r in d["grupos"]], default=1) or 1
    totn = (d["niv"].get(1,0)+d["niv"].get(2,0)+d["niv"].get(3,0)) or 1
    H = []
    A = H.append
    A(f'<div style="font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:640px;margin:0 auto;color:#1a2230">')
    A(f'<h1 style="font-size:22px;margin:0 0 2px">💰 Finanças — {mes_label(mes)}</h1>')
    A(f'<p style="color:#5b6776;margin:0 0 18px;font-size:14px">Relatório mensal do PIrrai</p>')
    # KPIs
    A('<table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:18px"><tr>')
    for lbl, val, col in [("Despesas", -d["desp"], "#d1242f"), ("Receitas", d["rec"], "#1a7f37"),
                          ("Saldo", saldo, "#1a7f37" if saldo>=0 else "#d1242f")]:
        A(f'<td style="padding:12px;background:#f5f7fa;border-radius:10px;width:33%"><div style="color:#5b6776;font-size:12px">{lbl}</div>'
          f'<div style="font-size:18px;font-weight:700;color:{col}">{brl(val)}</div></td><td style="width:8px"></td>')
    A('</tr></table>')
    if d["exc"]:
        A(f'<p style="font-size:13px;color:#5b6776;margin:-8px 0 14px">+ excepcionais (fora do normal): <b style="color:#c2410c">{brl(d["exc"])}</b></p>')
    A(f'<p style="font-size:13px;color:#5b6776">Despesas recorrentes: <b>{brl(d["desp"])}</b>{dtxt} · {d["n"]} transações'
      + (f' · <b style="color:#c2410c">{d["semcat"]} sem categoria</b>' if d["semcat"] else '') + '</p>')
    # Estrutura por nível
    A('<h3 style="font-size:15px;margin:22px 0 8px">Estrutura de gasto (essencialidade)</h3>')
    for nv in (1, 2, 3):
        v = d["niv"].get(nv, 0)
        if not v: continue
        A(f'<div style="margin:6px 0"><div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:2px">'
          f'<span>{NL[nv]}</span><span><b>{brl(v)}</b> · {v*100//totn}%</span></div>{bar(v*100/totn, NC[nv])}</div>')
    # Distribuição por pessoa
    ppl = [(p, v) for p, v in d["pessoa"].items() if (v[1]+v[2]+v[3]) > 0]
    if len(ppl) >= 1:
        A('<h3 style="font-size:15px;margin:22px 0 8px">Distribuição por pessoa (N1/N2/N3)</h3>')
        order = {"Ayla":0, "Rodrigo":1, "Casa":2}
        for p, v in sorted(ppl, key=lambda x: order.get(x[0], 9)):
            base = v[1]+v[2]+v[3] or 1
            A(f'<div style="margin:8px 0 4px"><b>{p}</b> <span style="color:#5b6776;font-size:12px">N1+N2+N3 {brl(base)}</span></div>')
            A('<table width="100%" cellspacing="0" style="border-radius:6px;overflow:hidden"><tr>')
            for nv in (1, 2, 3):
                if v[nv] <= 0: continue
                A(f'<td style="background:{NC[nv]};height:22px;width:{v[nv]*100//base}%;color:#fff;font-size:11px;font-weight:700;text-align:center">{v[nv]*100//base}%</td>')
            A('</tr></table>')
    # Despesas por grupo
    if d["grupos"]:
        A('<h3 style="font-size:15px;margin:22px 0 8px">Despesas por grupo</h3>')
        pal = ["#2f81f7","#3fb950","#ef6c00","#a371f7","#f85149","#00838f","#d29922","#6e7681"]
        for i, r in enumerate(d["grupos"]):
            A(f'<div style="margin:6px 0"><div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:2px">'
              f'<span>{r[0]}</span><span><b>{brl(r[1])}</b></span></div>{bar(r[1]*100/maxg, pal[i%len(pal)])}</div>')
    # Top categorias
    if d["cats"]:
        A('<h3 style="font-size:15px;margin:22px 0 8px">Top categorias</h3><table width="100%" cellspacing="0" style="font-size:13px">')
        for r in d["cats"]:
            A(f'<tr><td style="padding:4px 0;border-bottom:1px solid #eef1f5">{r[0]}</td>'
              f'<td style="padding:4px 0;border-bottom:1px solid #eef1f5;text-align:right;color:#d1242f">{brl(r[1])}</td></tr>')
        A('</table>')
    # Orçamento
    if d["orc"]:
        A('<h3 style="font-size:15px;margin:22px 0 8px">Orçamento do mês</h3>')
        for r in d["orc"]:
            p = r[2]*100//r[1] if r[1] else 0
            col = "#d1242f" if p>=100 else ("#d29922" if p>=80 else "#1a7f37")
            A(f'<div style="margin:6px 0"><div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:2px">'
              f'<span>{r[0]}</span><span>{brl(r[2])} / {brl(r[1])} · <b style="color:{col}">{p}%</b></span></div>{bar(p, col)}</div>')
    A('<p style="margin:26px 0 6px;font-size:13px"><a href="https://pirrai.tail414b9b.ts.net:8443/financas" style="color:#1f6feb">Abrir o painel completo →</a></p>')
    A('<p style="color:#8b98a9;font-size:11px;margin-top:18px">Gerado automaticamente pelo PIrrai. Movimentações (transferências/faturas/investimentos) não entram nos totais.</p>')
    A('</div>')
    return "\n".join(H)

def send(html, mes):
    user = os.environ.get("EMAIL_USER"); pw = os.environ.get("EMAIL_PASS")
    host = os.environ.get("SMTP_HOST"); port = int(os.environ.get("SMTP_PORT", "465"))
    to = os.environ.get("USER_EMAIL") or user
    if not all([user, pw, host, to]):
        print("email.env/config.env incompleto — não enviei", file=sys.stderr); return False
    m = EmailMessage()
    m["Subject"] = f"💰 Finanças — {mes_label(mes)}"
    m["From"] = user; m["To"] = to
    m.set_content("Seu cliente não exibe HTML. Abra o painel: https://pirrai.tail414b9b.ts.net:8443/financas")
    m.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as s:
        s.login(user, pw); s.send_message(m)
    print(f"relatório enviado para {to} ({mes_label(mes)})")
    return True

def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    mes = None
    if "--mes" in args: mes = args[args.index("--mes")+1]
    if not mes: mes = prev_month(datetime.date.today())
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    d = compute(con, mes); con.close()
    html = render_html(mes, d)
    if dry:
        out = os.path.join("/tmp", f"finance_report_{mes}.html")
        open(out, "w").write(html)
        print(f"[dry] {out}  (despesa {brl(d['desp'])}, receita {brl(d['rec'])}, {d['n']} txs)")
    else:
        send(html, mes)

if __name__ == "__main__":
    main()
