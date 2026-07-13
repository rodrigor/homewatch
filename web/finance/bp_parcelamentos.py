"""Parcelamentos (F5) — compras parceladas.

Modelo: cada parcelamento é 1 linha em `installments`; as parcelas NÃO viram
transações agendadas (evita corromper saldo/relatórios) — são PROJETADAS a partir
de start_date + n_total. Uma parcela conta como "paga" quando seu vencimento já
passou; a cobrança real entra normalmente pelo OFX quando acontece.
"""
import datetime
from calendar import monthrange
from flask import Blueprint, request, render_template, redirect, url_for, flash

from core import db, login_required, parse_cents, brl

bp = Blueprint("parc", __name__)


def _add_months(y, m, d, k):
    """data (y,m,d) + k meses, com o dia limitado ao fim do mês."""
    m2 = m + k; y2 = y
    while m2 > 12:
        m2 -= 12; y2 += 1
    return f"{y2:04d}-{m2:02d}-{min(d, monthrange(y2, m2)[1]):02d}"


def parcelas_of(inst, today=None):
    """lista de parcelas projetadas: [{n, date, amount, paga}]. Sinal segue o total.
    O resto do arredondamento vai na 1ª parcela (convenção de cartão)."""
    today = today or datetime.date.today().isoformat()
    n = int(inst["n_total"] or 1)
    mag_total = abs(inst["total"] or 0)
    mag_base = abs(inst["amount"] or 0)
    rem = mag_total - mag_base * n
    sign = -1 if (inst["total"] or 0) < 0 else 1
    y, m, d = (int(x) for x in str(inst["start_date"])[:10].split("-"))
    out = []
    for k in range(n):
        mag = mag_base + (rem if k == 0 else 0)
        dt = _add_months(y, m, d, k)
        out.append({"n": k + 1, "date": dt, "amount": sign * mag, "paga": dt <= today})
    return out


def _progress(inst, today=None):
    ps = parcelas_of(inst, today)
    pagas = [p for p in ps if p["paga"]]
    faltam = [p for p in ps if not p["paga"]]
    return {
        "id": inst["id"], "descricao": inst["description"], "category": inst["category"],
        "favorecido": inst["favorecido"], "account_id": inst["account_id"],
        "n_total": inst["n_total"], "total": inst["total"], "amount": inst["amount"],
        "n_pagas": len(pagas), "n_faltam": len(faltam),
        "restante": sum(p["amount"] for p in faltam),
        "proxima": faltam[0] if faltam else None,
        "parcelas": ps,
    }


def future_commitments(con, months=3, today=None):
    """soma das parcelas em aberto (vencimento no futuro) nos próximos `months` meses,
    agrupada por conta. Retorna (por_conta:list, total:int)."""
    today = today or datetime.date.today().isoformat()
    ty, tm, _ = (int(x) for x in today.split("-"))
    limite = _add_months(ty, tm, 28, months)  # fim da janela (~fim do mês +months)
    por_conta = {}
    total = 0
    for inst in con.execute("SELECT * FROM installments WHERE COALESCE(cancelled,0)=0").fetchall():
        for p in parcelas_of(inst, today):
            if not p["paga"] and today < p["date"] <= limite:
                por_conta[inst["account_id"]] = por_conta.get(inst["account_id"], 0) + p["amount"]
                total += p["amount"]
    return por_conta, total


@bp.route("/parcelamentos")
@login_required
def parcelamentos():
    c = db()
    insts = c.execute("SELECT * FROM installments WHERE COALESCE(cancelled,0)=0 ORDER BY id DESC").fetchall()
    itens = [_progress(i) for i in insts]
    # ordena: com parcelas faltando primeiro, depois por próxima data
    itens.sort(key=lambda x: (x["n_faltam"] == 0, x["proxima"]["date"] if x["proxima"] else "9999"))
    accs = c.execute("SELECT id,name,color FROM accounts ORDER BY name").fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY name").fetchall()
    por_conta, fut_total = future_commitments(c, 3)
    c.close()
    acc_name = {a["id"]: a["name"] for a in accs}
    aberto_total = sum(x["restante"] for x in itens)
    return render_template("parcelamentos.html", itens=itens, accs=accs, cats=cats,
                           acc_name=acc_name, hoje=datetime.date.today().isoformat(),
                           aberto_total=aberto_total, fut_total=fut_total,
                           fut_conta=[(acc_name.get(k, "—"), v) for k, v in sorted(por_conta.items())])


@bp.route("/api/parcelamento/new", methods=["POST"])
@login_required
def api_parcelamento_new():
    f = request.form
    desc = (f.get("descricao") or "").strip()
    total = parse_cents(f.get("valor_total", ""))
    try:
        n = int(f.get("n_parcelas") or 0)
    except ValueError:
        n = 0
    acc = f.get("conta") or None
    data = (f.get("data_primeira") or "").strip()
    if not desc or total is None or total == 0 or n < 2 or not data:
        flash("Preencha descrição, valor total, nº de parcelas (≥2), conta e data da 1ª parcela.")
        return redirect(url_for("parc.parcelamentos"))
    # despesa = negativo; receita = positivo
    mag = abs(total)
    total = -mag if f.get("tipo", "despesa") == "despesa" else mag
    base = (mag // n) * (1 if total > 0 else -1)   # parcela padrão (resto vai na 1ª, na projeção)
    c = db()
    c.execute("""INSERT INTO installments(total,amount,n_total,n_current,start_date,description,
                 account_id,category,favorecido,tx_type,cancelled,created_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,0,datetime('now','localtime'))""",
              (total, base, n, 0, data, desc, int(acc) if acc else None,
               f.get("categoria") or None, f.get("favorecido") or None,
               "receita" if total > 0 else "despesa"))
    c.commit(); c.close()
    flash(f"Parcelamento criado: {desc} — {n}× de {brl(abs(base))}.")
    return redirect(url_for("parc.parcelamentos"))


@bp.route("/api/parcelamento/<int:pid>/cancel", methods=["POST"])
@login_required
def api_parcelamento_cancel(pid):
    c = db()
    c.execute("UPDATE installments SET cancelled=1 WHERE id=?", (pid,))
    c.commit(); c.close()
    return {"ok": True}


@bp.route("/api/parcelamento/<int:pid>/delete", methods=["POST"])
@login_required
def api_parcelamento_del(pid):
    c = db()
    c.execute("DELETE FROM installments WHERE id=?", (pid,))
    c.commit(); c.close()
    return {"ok": True}
