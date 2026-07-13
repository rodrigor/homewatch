"""Listagem/edição de transações, lançamento manual, split e APIs de transação."""
import os, datetime, subprocess
from flask import Blueprint, request, redirect, url_for, flash, render_template

from core import (ROOT, FINANCE_SH, db, login_required, parse_cents, run_bg,
                  STATUSES, STATUS_GLYPH, SRC_ICONS, SRC_ICONS_LABELS,
                  tot_by_currency, val_label_for)
import finance_rules

bp = Blueprint("tx", __name__)


@bp.route("/transacoes")
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
        where.append("COALESCE(t.nivel, (SELECT nivel FROM categories WHERE name=t.category), t.email_hint_nivel, 0)=?"); params.append(int(f_cat[1]))
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
    return render_template("transacoes.html", mes=mes, rows=rows, accs=accs, cat_groups=cat_groups,
                           acolor=acolor, statuses=STATUSES, glyph=STATUS_GLYPH, show_conta=(not f_conta),
                           f_conta=f_conta, f_cat=f_cat, f_status=f_status, q=q, tot=tot,
                           totais=tot_by_currency(rows), val_label=val_label_for(rows), de=de, ate=ate,
                           src_icons=SRC_ICONS, src_labels=SRC_ICONS_LABELS)


@bp.route("/api/tx/<int:tid>", methods=["POST"])
@login_required
def api_tx(tid):
    field = request.form.get("field"); value = request.form.get("value", "")
    if field not in {"date", "datetime", "description", "merchant", "favorecido", "category", "status", "account_id", "amount", "excepcional", "nivel"}:
        return {"ok": False, "err": "campo inválido"}, 400
    c = db()
    if field == "nivel":   # override de essencialidade por lançamento; '' = auto (herda da categoria)
        c.execute("UPDATE transactions SET nivel=? WHERE id=?", (int(value) if value in ("0", "1", "2", "3") else None, tid))
    elif field == "amount":
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


@bp.route("/api/tx/<int:tid>/delete", methods=["POST"])
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


@bp.route("/api/tx/new", methods=["POST"])
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
    run_bg([os.path.join(ROOT, "finance_alerts.sh")])
    return {"ok": True}


@bp.route("/api/tx/<int:tid>/split", methods=["POST"])
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
@bp.route("/transacoes/nova", methods=["GET", "POST"])
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
        return redirect(url_for("tx.transacoes"))
    return render_template("nova.html", accs=accs, cats=cats, hoje=datetime.date.today().isoformat())
