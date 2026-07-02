"""Dashboard (Resumo mensal) e o fragmento de transações dos modais."""
import json, datetime
from flask import Blueprint, request, render_template

from core import (db, login_required, NOTRANSFER, STATUSES, STATUS_GLYPH,
                  SRC_ICONS, SRC_ICONS_LABELS, tot_by_currency, val_label_for)

bp = Blueprint("dash", __name__)


@bp.route("/financas")
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
    return render_template("financas.html", mes=mes, desp=desp, exc=exc, rec=rec, n=n, pend=pend,
                           grupos=grupos, niv_detail=niv_detail, orc=orc, maxg=maxg, totg=totg, meses=meses,
                           n1=n1, n2=n2, n3=n3, n0=n0, obrigatorio=obrigatorio, salario_base=salario_base,
                           acolor=acolor, pessoas=pessoas, orcserie_json=json.dumps(orcserie))


# ---------- transações de um recorte (modal do Resumo) ----------
@bp.route("/api/cat_tx")
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
    return render_template("cat_tx_fragment.html",
                           rows=rows, accs=accs, cat_groups=cat_groups, acolor=acolor,
                           statuses=STATUSES, glyph=STATUS_GLYPH, tot=tot,
                           totais=tot_by_currency(rows), val_label=val_label_for(rows),
                           src_icons=SRC_ICONS, src_labels=SRC_ICONS_LABELS)
