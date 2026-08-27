#!/usr/bin/env python3
"""finance_installments.py — parcelamento de compra no cartão.
A partir de UMA transação já lançada (a 1ª parcela, vinda de OFX/email/manual),
gera as N-1 transações futuras (status='agendado'), mesma categoria/nível/conta,
uma por mês (mesmo dia, com clamp de fim de mês via dateutil). O reconciliador
(ofx_parser.reconcile) já casa essas linhas sozinho quando o extrato do mês
chegar (valor + data ±2 dias + mesma conta).

Uso via CLI:
  finance_installments.py add <tx_id_primeira_parcela> <n_total>
  finance_installments.py list
  finance_installments.py cancel <installment_id>
  finance_installments.py check-missing   # parcelas 'agendado' com data já vencida há dias
"""
import os, sys, json, sqlite3
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("FINANCE_DB", os.path.join(ROOT, "finance.db"))


def con():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA busy_timeout=5000")
    return c


def add(tx_id, n_total):
    n_total = int(n_total)
    if n_total < 2:
        return {"error": "n_total precisa ser >= 2 (senão não é parcelamento)"}
    c = con()
    row = c.execute(
        "SELECT date,amount,description,category,account_id,favorecido,nivel,tx_type,installment_id "
        "FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if not row:
        return {"error": f"transação #{tx_id} não encontrada"}
    tdate, amount, desc, cat, acc_id, fav, nivel, tx_type, existing_plan = row
    if existing_plan:
        return {"error": f"transação #{tx_id} já faz parte do plano de parcelamento #{existing_plan}"}

    start = date.fromisoformat(tdate)
    total = amount * n_total  # amount já é negativo p/ despesa; total mantém o sinal

    cur = c.execute(
        "INSERT INTO installments(total,amount,n_total,n_current,start_date,description,"
        "account_id,category,favorecido,tx_type,cancelled,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,0,datetime('now','localtime'))",
        (total, amount, n_total, 1, tdate, desc, acc_id, cat, fav, tx_type))
    plan_id = cur.lastrowid

    # marca a 1a parcela (a transação que já existia) como parte do plano,
    # e deixa a descrição consistente com as demais
    c.execute("UPDATE transactions SET installment_id=?, description=? WHERE id=?",
              (plan_id, f"{desc} (1/{n_total})", tx_id))

    created = [tx_id]
    for i in range(2, n_total + 1):
        d = start + relativedelta(months=i - 1)
        new_desc = f"{desc} ({i}/{n_total})"
        cur2 = c.execute(
            "INSERT INTO transactions(date,amount,description,category,account_id,source,status,"
            "favorecido,nivel,tx_type,installment_id) VALUES(?,?,?,?,?,'manual','agendado',?,?,?,?)",
            (d.isoformat(), amount, new_desc, cat, acc_id, fav, nivel, tx_type, plan_id))
        created.append(cur2.lastrowid)
    c.commit()
    return {"plan_id": plan_id, "n_total": n_total, "amount_cents": amount,
            "start_date": tdate, "created_tx_ids": created}


def list_plans():
    c = con()
    rows = c.execute(
        "SELECT id,description,amount,n_total,start_date,account_id,cancelled FROM installments ORDER BY id DESC").fetchall()
    out = []
    for pid, desc, amount, n_total, start, acc_id, cancelled in rows:
        prog = c.execute(
            "SELECT status, date, id FROM transactions WHERE installment_id=? ORDER BY date", (pid,)).fetchall()
        done = sum(1 for s, _, _ in prog if s in ("conciliado", "confirmado"))
        pending = [(d, tid) for s, d, tid in prog if s == "agendado"]
        next_due = pending[0][0] if pending else None
        remaining_cents = amount * len(pending)
        out.append({
            "plan_id": pid, "description": desc, "amount_cents": amount, "n_total": n_total,
            "start_date": start, "account_id": acc_id, "cancelled": bool(cancelled),
            "done": done, "next_due": next_due, "remaining_cents": remaining_cents,
            "remaining_n": len(pending),
        })
    return out


def cancel(plan_id):
    c = con()
    removed = c.execute(
        "SELECT id FROM transactions WHERE installment_id=? AND status='agendado'", (plan_id,)).fetchall()
    ids = [r[0] for r in removed]
    if ids:
        c.executemany("DELETE FROM transactions WHERE id=?", [(i,) for i in ids])
    c.execute("UPDATE installments SET cancelled=1 WHERE id=?", (plan_id,))
    c.commit()
    return {"plan_id": plan_id, "removed_tx_ids": ids}


_MISSING_TAG = "[parcela_atrasada_alertada]"


def check_missing(grace_days=5):
    """Parcelas 'agendado' cuja data já passou há mais de grace_days sem serem
    conciliadas (ou seja, o extrato do mês já devia ter chegado e não bateu)."""
    c = con()
    limit = (date.today() - timedelta(days=grace_days)).isoformat()
    rows = c.execute(
        "SELECT t.id, t.description, t.amount, t.date, i.id, COALESCE(t.notes,'') "
        "FROM transactions t JOIN installments i ON t.installment_id=i.id "
        "WHERE t.status='agendado' AND t.date<=? AND i.cancelled=0", (limit,)).fetchall()
    return [{"tx_id": r[0], "description": r[1], "amount_cents": r[2], "date": r[3],
              "plan_id": r[4], "already_alerted": _MISSING_TAG in r[5]} for r in rows]


def check_missing_new(grace_days=5):
    """Como check_missing(), mas só devolve as que AINDA não foram alertadas, e já
    marca as devolvidas como alertadas (dedupe — não repete aviso toda semana)."""
    c = con()
    items = [i for i in check_missing(grace_days) if not i["already_alerted"]]
    for i in items:
        row = c.execute("SELECT COALESCE(notes,'') FROM transactions WHERE id=?", (i["tx_id"],)).fetchone()
        notes = (row[0] + " " + _MISSING_TAG).strip() if row else _MISSING_TAG
        c.execute("UPDATE transactions SET notes=? WHERE id=?", (notes, i["tx_id"]))
    c.commit()
    return items


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "add":
        print(json.dumps(add(sys.argv[2], sys.argv[3]), ensure_ascii=False))
    elif cmd == "list":
        print(json.dumps(list_plans(), ensure_ascii=False))
    elif cmd == "cancel":
        print(json.dumps(cancel(sys.argv[2]), ensure_ascii=False))
    elif cmd == "check-missing":
        print(json.dumps(check_missing(), ensure_ascii=False))
    elif cmd == "check-missing-new":
        print(json.dumps(check_missing_new(), ensure_ascii=False))
    else:
        print("uso: finance_installments.py add <tx_id> <n_total> | list | cancel <plan_id> | check-missing")
        sys.exit(1)
