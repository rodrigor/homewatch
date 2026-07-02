"""Regras de classificação, limites mensais, grupos/níveis e conciliação OFX."""
import os, datetime
from flask import Blueprint, request, redirect, url_for, flash, render_template

from core import ROOT, db, login_required, parse_cents, run_bg
import ofx_parser, finance_rules

bp = Blueprint("regras", __name__)

RULE_FIELDS = [("favorecido", "Favorecido"), ("description", "Descrição"),
               ("merchant", "Estabelecimento"), ("qualquer", "Qualquer campo")]


def ensure_category(c, name):
    if name and not c.execute("SELECT 1 FROM categories WHERE name=?", (name,)).fetchone():
        c.execute("INSERT INTO categories(name,icon) VALUES(?, '🏷️')", (name,))


@bp.route("/regras")
@login_required
def regras():
    c = db()
    rows = c.execute("SELECT * FROM rules ORDER BY id").fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY name").fetchall()
    accs = c.execute("SELECT id,name FROM accounts ORDER BY name").fetchall()
    c.close()
    return render_template("regras.html", rows=rows, cats=cats, accs=accs, fields=RULE_FIELDS)


@bp.route("/api/rule/new", methods=["POST"])
@login_required
def api_rule_new():
    f = request.form
    field = f.get("field", "favorecido"); pattern = (f.get("pattern") or "").strip(); category = (f.get("category") or "").strip()
    if not pattern or not category: return {"ok": False, "err": "preencha texto e categoria"}, 400
    if field not in {"favorecido", "description", "merchant", "qualquer"}: field = "favorecido"
    def _int(v):
        v = (v or "").strip(); return int(v) if v.isdigit() else None
    acc = _int(f.get("conta")); dmin = _int(f.get("dom_min")); dmax = _int(f.get("dom_max"))
    sfav = (f.get("set_fav") or "").strip() or None
    c = db()
    ensure_category(c, category)
    c.execute("INSERT INTO rules(field,pattern,category,account_id,dom_min,dom_max,set_fav) VALUES(?,?,?,?,?,?,?)",
              (field, pattern, category, acc, dmin, dmax, sfav))
    c.commit(); c.close(); return {"ok": True}


@bp.route("/api/rule/<int:rid>", methods=["POST"])
@login_required
def api_rule(rid):
    field = request.form.get("field"); value = request.form.get("value", "").strip()
    if field not in {"field", "pattern", "category", "account_id", "dom_min", "dom_max", "set_fav"}:
        return {"ok": False, "err": "campo inválido"}, 400
    if field in ("pattern", "category") and not value: return {"ok": False, "err": "não pode ficar vazio"}, 400
    c = db()
    if field == "category": ensure_category(c, value)
    if field in ("account_id", "dom_min", "dom_max"):
        c.execute(f"UPDATE rules SET {field}=? WHERE id=?", (int(value) if value.isdigit() else None, rid))
    elif field == "set_fav":
        c.execute("UPDATE rules SET set_fav=? WHERE id=?", (value or None, rid))
    else:
        c.execute(f"UPDATE rules SET {field}=? WHERE id=?", (value, rid))
    c.commit(); c.close()
    return {"ok": True}


@bp.route("/api/rule/<int:rid>/delete", methods=["POST"])
@login_required
def api_rule_del(rid):
    c = db(); c.execute("DELETE FROM rules WHERE id=?", (rid,)); c.commit(); c.close()
    return {"ok": True}


@bp.route("/regras/aplicar", methods=["POST"])
@login_required
def regras_aplicar():
    c = db(); n = finance_rules.apply_rules(c); c.close()
    flash(f"Regras aplicadas: {n} transação(ões) reclassificada(s).")
    return redirect(url_for("regras.regras"))


@bp.route("/limites")
@login_required
def limites():
    mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    c = db()
    rows = c.execute("""SELECT cat.name, cat.icon, COALESCE(b.limit_amount,0) lim,
        COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=cat.name AND amount<0 AND substr(date,1,7)=?),0) spent
        FROM categories cat LEFT JOIN budgets b ON b.category=cat.name AND b.month='*'
        WHERE cat.name<>'Receitas' ORDER BY (CASE WHEN b.limit_amount>0 THEN 0 ELSE 1 END), cat.name""", (mes,)).fetchall()
    c.close()
    return render_template("limites.html", rows=rows, mes=mes)


@bp.route("/api/limite", methods=["POST"])
@login_required
def api_limite():
    name = request.form.get("name", ""); value = request.form.get("value", "").strip()
    mes = datetime.date.today().strftime("%Y-%m")
    c = db()
    if not value:
        c.execute("DELETE FROM budgets WHERE category=? AND month='*'", (name,))
        c.execute("DELETE FROM budget_alerts WHERE category=?", (name,))
    else:
        cents = parse_cents(value)
        if cents is None: c.close(); return {"ok": False, "err": "valor inválido"}, 400
        c.execute("""INSERT INTO budgets(category,month,limit_amount) VALUES(?,'*',?)
                     ON CONFLICT(category,month) DO UPDATE SET limit_amount=excluded.limit_amount""", (name, abs(cents)))
        c.execute("DELETE FROM budget_alerts WHERE category=? AND month=?", (name, mes))  # permite re-alertar com novo limite
    c.commit(); c.close(); return {"ok": True}


@bp.route("/grupos")
@login_required
def grupos():
    c = db()
    cats = c.execute("SELECT name, icon, grupo, is_transfer, COALESCE(nivel,0) nivel FROM categories ORDER BY COALESCE(grupo,'zzz'), name").fetchall()
    gs = [r[0] for r in c.execute("SELECT DISTINCT grupo FROM categories WHERE grupo IS NOT NULL AND grupo<>'' ORDER BY grupo")]
    c.close()
    return render_template("grupos.html", cats=cats, gs=gs)


@bp.route("/api/cat", methods=["POST"])
@login_required
def api_cat():
    name = request.form.get("name", ""); field = request.form.get("field", "grupo"); value = request.form.get("value", "").strip()
    c = db()
    if field == "is_transfer":
        c.execute("UPDATE categories SET is_transfer=? WHERE name=?", (1 if value in ("1", "true", "on") else 0, name))
    elif field == "grupo":
        c.execute("UPDATE categories SET grupo=? WHERE name=?", (value or None, name))
    elif field == "nivel":
        try:
            n = int(value)
            if n not in (0, 1, 2, 3): raise ValueError()
            c.execute("UPDATE categories SET nivel=? WHERE name=?", (n, name))
        except ValueError:
            c.close(); return {"ok": False, "err": "nivel inválido (0-3)"}, 400
    else:
        c.close(); return {"ok": False, "err": "campo inválido"}, 400
    c.commit(); c.close(); return {"ok": True}


@bp.route("/conciliacao", methods=["GET", "POST"])
@login_required
def conciliacao():
    c = db()
    if request.method == "POST":
        f = request.files.get("ofx")
        if not f or not f.filename:
            flash("Selecione um arquivo OFX."); c.close(); return redirect(url_for("regras.conciliacao"))
        raw = ofx_parser.decode_ofx(f.read())
        txns = ofx_parser.parse(raw)
        matched, imported, dup = ofx_parser.reconcile(c, txns, ofx_parser.parse_account(raw))
        c.execute("INSERT INTO ofx_imports(filename,matched,unmatched) VALUES(?,?,?)",
                  (f.filename, matched, imported)); c.commit()
        flash(f"OFX “{f.filename}”: {len(txns)} lidas · {matched} conciliadas · {imported} novas · {dup} já existentes")
        c.close()
        fin = os.path.join(ROOT, "finance.sh")
        # pós-processamento em background (classificação, favorecidos, pendências)
        run_bg([fin, "classify-all"],
               ["python3", os.path.join(ROOT, "finance_rules.py"), "favorecidos"],
               [fin, "ask-pending"])
        return redirect(url_for("regras.conciliacao"))
    last = c.execute("SELECT * FROM ofx_imports ORDER BY id DESC LIMIT 6").fetchall()
    nimp = c.execute("SELECT COUNT(*) FROM transactions WHERE status='importado'").fetchone()[0]
    ncon = c.execute("SELECT COUNT(*) FROM transactions WHERE status='conciliado'").fetchone()[0]
    c.close()
    return render_template("conciliacao.html", last=last, nimp=nimp, ncon=ncon)
