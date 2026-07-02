"""Contas (CRUD + saldos), transferências entre contas e investimentos."""
import json, datetime, sqlite3, uuid
from flask import Blueprint, request, render_template

from core import db, login_required, TITULARES

bp = Blueprint("contas", __name__)

ACCT_TYPES = ["corrente", "poupança", "credito", "espécie", "vale", "investimento", "conta"]


@bp.route("/contas")
@login_required
def contas():
    c = db()
    rows = c.execute("""
        SELECT a.*,
               COALESCE(a.opening_balance,0) + COALESCE(SUM(t.amount),0) AS saldo,
               COALESCE(a.currency,'BRL') AS moeda,
               COUNT(t.id) AS usos
        FROM accounts a
        LEFT JOIN transactions t ON t.account_id = a.id
        GROUP BY a.id ORDER BY a.name""").fetchall()
    c.close()
    CURRENCIES = ["BRL", "USD", "EUR", "GBP", "ARS", "UYU"]
    # patrimônio por moeda
    saldos_map = {}
    for r in rows:
        saldos_map[r["moeda"]] = saldos_map.get(r["moeda"], 0) + r["saldo"]
    saldos = sorted(saldos_map.items())
    # dados p/ o modal de edição
    accts = {r["id"]: {"id": r["id"], "name": r["name"] or "", "titular": r["titular"] or "",
                       "bank": r["bank"] or "", "numero": r["numero"] or "", "type": r["type"] or "corrente",
                       "currency": r["moeda"], "color": r["color"] or "#2f81f7",
                       "opening_balance": r["opening_balance"] or 0,
                       "iof_rate": r["iof_rate"] or 0, "spread_rate": r["spread_rate"] or 0,
                       "entra_orcamento": 1 if (r["entra_orcamento"] is None or r["entra_orcamento"]) else 0} for r in rows}
    return render_template("contas.html", rows=rows, saldos=saldos, types=ACCT_TYPES,
                           titulares=TITULARES, currencies=CURRENCIES, accts_json=json.dumps(accts))


def _pct_frac(v):   # "3,5" (percentual) -> 0.035 (fração)
    try: return float((v or "0").replace(",", ".")) / 100.0
    except Exception: return 0.0


@bp.route("/api/account/new", methods=["POST"])
@login_required
def api_account_new():
    f = request.form; name = (f.get("name") or "").strip()
    if not name: return {"ok": False, "err": "nome obrigatório"}, 400
    ob_raw = f.get("opening_balance", "0")
    try: ob = int(ob_raw)
    except Exception: ob = 0
    currency = (f.get("currency") or "BRL").strip().upper() or "BRL"
    iof = _pct_frac(f.get("iof_rate")); spread = _pct_frac(f.get("spread_rate"))
    orc = 0 if f.get("entra_orcamento", "1") in ("0", "false", "off") else 1
    c = db()
    try:
        c.execute("INSERT INTO accounts(name,bank,numero,type,color,titular,opening_balance,currency,iof_rate,spread_rate,entra_orcamento) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (name, f.get("bank") or None, f.get("numero") or None, f.get("type") or "conta",
                   f.get("color") or "#888", f.get("titular") or None, ob, currency, iof, spread, orc))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "já existe conta com esse nome"}, 400
    c.close(); return {"ok": True}


@bp.route("/api/account/<int:aid>/save", methods=["POST"])
@login_required
def api_account_save(aid):
    f = request.form; name = (f.get("name") or "").strip()
    if not name: return {"ok": False, "err": "nome obrigatório"}, 400
    try: ob = int(f.get("opening_balance") or 0)
    except Exception: ob = 0
    currency = (f.get("currency") or "BRL").strip().upper() or "BRL"
    c = db()
    try:
        orc = 0 if f.get("entra_orcamento", "1") in ("0", "false", "off") else 1
        c.execute("""UPDATE accounts SET name=?, titular=?, bank=?, numero=?, type=?, color=?,
                     currency=?, opening_balance=?, iof_rate=?, spread_rate=?, entra_orcamento=? WHERE id=?""",
                  (name, f.get("titular") or None, f.get("bank") or None, f.get("numero") or None,
                   f.get("type") or "conta", f.get("color") or "#888", currency, ob,
                   _pct_frac(f.get("iof_rate")), _pct_frac(f.get("spread_rate")), orc, aid))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "nome duplicado"}, 400
    c.close(); return {"ok": True}


@bp.route("/api/account/<int:aid>", methods=["POST"])
@login_required
def api_account(aid):
    field = request.form.get("field"); value = request.form.get("value", "").strip()
    if field not in {"name", "bank", "numero", "type", "color", "titular", "currency", "opening_balance", "iof_rate", "spread_rate"}:
        return {"ok": False, "err": "campo inválido"}, 400
    if field == "name" and not value:
        return {"ok": False, "err": "nome não pode ficar vazio"}, 400
    c = db()
    try:
        if field == "opening_balance":
            try: v = int(value)
            except Exception: c.close(); return {"ok": False, "err": "valor inválido"}, 400
            c.execute("UPDATE accounts SET opening_balance=? WHERE id=?", (v, aid))
        elif field in ("iof_rate", "spread_rate"):
            try: v = float((value or "0").replace(",", ".")) / 100.0   # UI em %, armazena fração
            except Exception: c.close(); return {"ok": False, "err": "taxa inválida"}, 400
            c.execute(f"UPDATE accounts SET {field}=? WHERE id=?", (v, aid))
        elif field == "currency":
            c.execute("UPDATE accounts SET currency=? WHERE id=?", (value.upper() or "BRL", aid))
        else:
            c.execute(f"UPDATE accounts SET {field}=? WHERE id=?", (value or None, aid))
        c.commit()
    except sqlite3.IntegrityError:
        c.close(); return {"ok": False, "err": "nome duplicado"}, 400
    c.close(); return {"ok": True}


@bp.route("/api/account/<int:aid>/delete", methods=["POST"])
@login_required
def api_account_del(aid):
    c = db()
    c.execute("UPDATE transactions SET account_id=NULL WHERE account_id=?", (aid,))
    c.execute("DELETE FROM accounts WHERE id=?", (aid,)); c.commit(); c.close()
    return {"ok": True}


@bp.route("/transferencia", methods=["GET", "POST"])
@login_required
def transferencia():
    c = db()
    accounts = c.execute("SELECT id, name, COALESCE(currency,'BRL') currency FROM accounts ORDER BY name").fetchall()
    msg = None
    if request.method == "POST":
        f = request.form
        de_id   = int(f.get("de_id") or 0)
        para_id = int(f.get("para_id") or 0)
        val_de_str   = f.get("val_de", "").replace(",", ".")
        val_para_str = (f.get("val_para") or "").replace(",", ".")
        data    = f.get("data") or datetime.date.today().isoformat()
        desc    = f.get("desc") or "Transferência"
        if not de_id or not para_id or de_id == para_id:
            msg = ("err", "Selecione contas de origem e destino diferentes.")
        else:
            try:
                val_de_cents = int(round(float(val_de_str) * 100))
            except Exception:
                val_de_cents = 0
            if val_de_cents <= 0:
                msg = ("err", "Valor de origem inválido.")
            else:
                # conta destino: se tiver val_para, usa; caso contrário igual ao de_id
                if val_para_str:
                    try: val_para_cents = int(round(float(val_para_str) * 100))
                    except Exception: val_para_cents = val_de_cents
                else:
                    val_para_cents = val_de_cents

                # descobrir moedas
                acc_de   = c.execute("SELECT currency FROM accounts WHERE id=?", (de_id,)).fetchone()
                acc_para = c.execute("SELECT currency FROM accounts WHERE id=?", (para_id,)).fetchone()
                moeda_de   = (acc_de["currency"]   if acc_de   else "BRL") or "BRL"
                moeda_para = (acc_para["currency"] if acc_para else "BRL") or "BRL"

                # fx_rate (VET, taxa cheia) = origem/destino quando cross-currency
                fx_rate = None
                if moeda_de != moeda_para and val_para_str:
                    try: fx_rate = round(val_de_cents / val_para_cents, 6)
                    except Exception: fx_rate = None

                # IOF/spread embutidos: incidem na perna em BRL de uma conversão,
                # derivados da taxa-padrão da conta global envolvida (o valor real é o bruto).
                iof_de = spread_de = iof_para = spread_para = None
                if moeda_de != moeda_para:
                    rr = c.execute("SELECT COALESCE(MAX(iof_rate),0), COALESCE(MAX(spread_rate),0) FROM accounts WHERE id IN (?,?)", (de_id, para_id)).fetchone()
                    r, s = (rr[0] or 0), (rr[1] or 0)
                    if r or s:
                        if moeda_de == "BRL":
                            comercial = val_de_cents / (1 + r + s)
                            iof_de = round(comercial * r); spread_de = round(comercial * s)
                        elif moeda_para == "BRL":
                            comercial = val_para_cents / (1 + r + s)
                            iof_para = round(comercial * r); spread_para = round(comercial * s)

                cat_transfer = "Transferência própria"
                nome_de   = next((a["name"] for a in accounts if a["id"] == de_id), str(de_id))
                nome_para = next((a["name"] for a in accounts if a["id"] == para_id), str(para_id))
                tgroup = uuid.uuid4().hex

                # débito (origem) — favorecido = conta destino
                c.execute("""INSERT INTO transactions(date,amount,amount_original,currency,fx_rate,description,category,favorecido,account_id,tx_type,source,status,transfer_group,iof_amount,spread_amount)
                             VALUES(?,?,?,?,?,?,?,?,?,'transfer','manual','confirmado',?,?,?)""",
                          (data, -val_de_cents, -val_de_cents, moeda_de, fx_rate, desc, cat_transfer, nome_para, de_id, tgroup, iof_de, spread_de))
                deb_id = c.lastrowid

                # crédito (destino) — favorecido = conta origem
                c.execute("""INSERT INTO transactions(date,amount,amount_original,currency,fx_rate,description,category,favorecido,account_id,tx_type,source,status,transfer_pair_id,transfer_group,iof_amount,spread_amount)
                             VALUES(?,?,?,?,?,?,?,?,?,'transfer','manual','confirmado',?,?,?,?)""",
                          (data, val_para_cents, val_para_cents, moeda_para, fx_rate, desc, cat_transfer, nome_de, para_id, deb_id, tgroup, iof_para, spread_para))
                cred_id = c.lastrowid

                # linkar o débito ao crédito (transfer_group já compartilhado)
                c.execute("UPDATE transactions SET transfer_pair_id=? WHERE id=?", (cred_id, deb_id))
                c.commit()

                fx_str = f" (câmbio {fx_rate:.4f})" if fx_rate else ""
                iof_str = f" · IOF R$ {(iof_de or iof_para or 0)/100:.2f}" if (iof_de or iof_para) else ""
                msg = ("ok", f"Transferência registrada: {nome_de} → {nome_para}, {moeda_de} {val_de_cents/100:.2f}{fx_str}{iof_str}")

    c.close()
    return render_template("transferencia.html", accounts=accounts, msg=msg,
                           today=datetime.date.today().isoformat())


@bp.route("/investimentos")
@login_required
def investimentos():
    c = db()
    # contas de investimento (tipo contendo 'invest' ou 'previdencia', ou todas com aportes/resgates)
    inv_accounts = c.execute("""
        SELECT a.id, a.name, COALESCE(a.currency,'BRL') currency,
               COALESCE(a.opening_balance,0) opening_balance
        FROM accounts a
        WHERE LOWER(a.type) LIKE '%invest%'
           OR LOWER(a.type) LIKE '%previdên%'
           OR LOWER(a.type) LIKE '%previden%'
           OR a.id IN (SELECT DISTINCT account_id FROM transactions WHERE tx_type='rendimento' AND account_id IS NOT NULL)
        ORDER BY a.name""").fetchall()

    rows = []
    for acc in inv_accounts:
        aid = acc["id"]
        moeda = acc["currency"]
        ob = acc["opening_balance"]

        aportes   = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND amount>0 AND tx_type='transfer'", (aid,)).fetchone()[0]
        resgates  = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND amount<0 AND tx_type='transfer'", (aid,)).fetchone()[0]
        rend_pos  = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND tx_type='rendimento' AND amount>0", (aid,)).fetchone()[0]
        rend_neg  = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account_id=? AND tx_type='rendimento' AND amount<0", (aid,)).fetchone()[0]
        rendimento = rend_pos + rend_neg
        saldo = ob + aportes + resgates + rendimento

        # última valorização snapshot
        last_val = c.execute("SELECT value, date FROM account_valuations WHERE account_id=? ORDER BY date DESC LIMIT 1", (aid,)).fetchone()

        total_aportado = ob + aportes + resgates  # capital investido líquido
        rent_pct = (rendimento / total_aportado * 100) if total_aportado != 0 else 0.0

        rows.append({"id": aid, "name": acc["name"], "currency": moeda,
                     "aportes": aportes, "resgates": resgates,
                     "rendimento": rendimento, "saldo": saldo,
                     "rent_pct": rent_pct,
                     "last_val_value": last_val["value"] if last_val else None,
                     "last_val_date": last_val["date"] if last_val else None})
    c.close()
    return render_template("investimentos.html", rows=rows)
