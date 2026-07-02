"""Favorecidos: relatório, detalhe, cadastro (CRUD) e normalização."""
import json, datetime, sqlite3
from flask import Blueprint, request, redirect, url_for, flash, render_template

from core import (db, login_required, NOTRANSFER, STATUSES, STATUS_GLYPH,
                  SRC_ICONS, SRC_ICONS_LABELS, tot_by_currency, val_label_for)
import finance_rules

bp = Blueprint("fav", __name__)

FAV_TIPOS = ["", "pessoa", "empresa", "órgão público", "outro"]


@bp.route("/favorecidos")
@login_required
def favorecidos():
    todos = request.args.get("todos"); mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    q = request.args.get("q", "").strip()
    dest = "COALESCE(NULLIF(favorecido,''),description)"
    where = ["amount<0", NOTRANSFER]; params = []
    if not todos: where.append("substr(date,1,7)=?"); params.append(mes)
    if q: where.append(f"{dest} LIKE ?"); params.append(f"%{q}%")
    c = db()
    rows = c.execute(f"""SELECT {dest} dest, COUNT(*) qt, -SUM(amount) total, MAX(COALESCE(category,'—')) cat
        FROM transactions WHERE {' AND '.join(where)} GROUP BY {dest} ORDER BY -SUM(amount) DESC""", params).fetchall()
    c.close()
    total = sum(r["total"] for r in rows); maxv = rows[0]["total"] if rows else 1
    return render_template("favorecidos.html", rows=rows, total=total, maxv=maxv, mes=mes, todos=todos, q=q)


@bp.route("/favorecido")
@login_required
def favorecido_det():
    nome = request.args.get("nome", "")
    todos = request.args.get("todos"); mes = request.args.get("mes", datetime.date.today().strftime("%Y-%m"))
    dest = "COALESCE(NULLIF(favorecido,''),description)"
    where = [f"{dest}=?"]; params = [nome]
    if not todos: where.append("substr(date,1,7)=?"); params.append(mes)
    c = db()
    rows = c.execute(f"""SELECT t.*, a.name acc FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        WHERE {' AND '.join(where)} ORDER BY t.date DESC, t.id DESC""", params).fetchall()
    accs = c.execute("SELECT id,name,color FROM accounts ORDER BY name").fetchall()
    cat_rows = c.execute("SELECT name, COALESCE(NULLIF(grupo,''),'(sem grupo)') g FROM categories ORDER BY g, name").fetchall()
    c.close()
    cat_groups = {}
    for r in cat_rows: cat_groups.setdefault(r["g"], []).append(r["name"])
    acolor = {a["id"]: (a["color"] or "#888") for a in accs}
    tot = sum(r["amount"] for r in rows)
    return render_template("favorecido_det.html", nome=nome, rows=rows, tot=tot,
                           totais=tot_by_currency(rows), val_label=val_label_for(rows),
                           mes=mes, todos=todos, accs=accs, cat_groups=cat_groups, acolor=acolor,
                           statuses=STATUSES, glyph=STATUS_GLYPH, src_icons=SRC_ICONS, src_labels=SRC_ICONS_LABELS)


@bp.route("/favorecidos/gerir")
@login_required
def favorecidos_gerir():
    c = db()
    rows = c.execute("SELECT f.*, (SELECT COUNT(*) FROM transactions WHERE favorecido=f.nome) usos FROM favorecidos f ORDER BY f.nome").fetchall()
    cats = c.execute("SELECT name FROM categories ORDER BY name").fetchall()
    c.close()
    favs = []
    for r in rows:
        try: al = json.loads(r["aliases"] or "[]")
        except Exception: al = []
        favs.append({"id": r["id"], "nome": r["nome"], "tipo": r["tipo"] or "", "documento": r["documento"] or "",
                     "cp": r["categoria_padrao"] or "", "aliases": ", ".join(al), "rec": r["recorrente"] or 0, "usos": r["usos"]})
    return render_template("favorecidos_gerir.html", favs=favs, cats=cats, tipos=FAV_TIPOS)


@bp.route("/api/favorecido/new", methods=["POST"])
@login_required
def api_favorecido_new():
    f = request.form; nome = (f.get("nome") or "").strip()
    if not nome: return {"ok": False, "err": "nome obrigatório"}, 400
    al = [a.strip() for a in (f.get("aliases") or "").split(",") if a.strip()]
    c = db()
    try:
        c.execute("INSERT INTO favorecidos(nome,tipo,documento,categoria_padrao,recorrente,aliases) VALUES(?,?,?,?,?,?)",
                  (nome, f.get("tipo") or None, f.get("documento") or None, f.get("categoria_padrao") or None,
                   1 if f.get("recorrente") in ("1", "true", "on") else 0, json.dumps(al, ensure_ascii=False)))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "já existe favorecido com esse nome"}, 400
    c.close(); return {"ok": True}


@bp.route("/api/favorecido/<int:fid>", methods=["POST"])
@login_required
def api_favorecido(fid):
    field = request.form.get("field"); value = request.form.get("value", "").strip()
    if field not in {"nome", "tipo", "documento", "categoria_padrao", "aliases", "notas", "recorrente", "nivel_padrao"}:
        return {"ok": False, "err": "campo inválido"}, 400
    c = db()
    if field == "aliases":
        al = [a.strip() for a in value.split(",") if a.strip()]
        c.execute("UPDATE favorecidos SET aliases=? WHERE id=?", (json.dumps(al, ensure_ascii=False), fid))
    elif field == "recorrente":
        c.execute("UPDATE favorecidos SET recorrente=? WHERE id=?", (1 if value in ("1", "true", "on") else 0, fid))
    elif field == "nome" and not value:
        c.close(); return {"ok": False, "err": "nome não pode ficar vazio"}, 400
    else:
        try:
            c.execute(f"UPDATE favorecidos SET {field}=? WHERE id=?", (value or None, fid))
        except sqlite3.IntegrityError:
            c.close(); return {"ok": False, "err": "nome duplicado"}, 400
    c.commit(); c.close(); return {"ok": True}


@bp.route("/api/favorecido/<int:fid>/delete", methods=["POST"])
@login_required
def api_favorecido_del(fid):
    c = db(); c.execute("DELETE FROM favorecidos WHERE id=?", (fid,)); c.commit(); c.close()
    return {"ok": True}


@bp.route("/favorecidos/aplicar", methods=["POST"])
@login_required
def favorecidos_aplicar():
    c = db(); n = finance_rules.apply_favorecidos(c); c.close()
    flash(f"Normalização aplicada: {n} lançamento(s) atualizados.")
    return redirect(url_for("fav.favorecidos_gerir"))
