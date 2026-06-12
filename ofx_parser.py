#!/usr/bin/env python3
"""ofx_parser.py — parser tolerante de OFX (SGML dos bancos BR e OFX 2.x/XML).
Extrai transações (date, cents, description, favorecido, memo, fitid) e os dados da conta
(BANKACCTFROM), e concilia com o banco local (dedupe por FITID, match por valor+data)."""
import re

BANK_NAMES = {"260": "Nubank", "1": "Banco do Brasil", "341": "Itaú", "33": "Santander",
              "104": "Caixa", "237": "Bradesco", "77": "Inter", "212": "Original",
              "336": "C6", "290": "PagBank", "380": "PicPay", "208": "BTG"}

def decode_ofx(b):
    """decodifica bytes de OFX tentando UTF-8 (Nubank) e caindo p/ latin-1 (bancos antigos)."""
    for enc in ("utf-8", "latin-1"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode("latin-1", "replace")

def _split_memo(memo):
    """separa descrição e favorecido. Em transferências/Pix o favorecido vem no MEMO:
    'Transferência Recebida - FULANO DE TAL - •••.123-•• - BCO ... ' -> ('Transferência Recebida','FULANO DE TAL')."""
    memo = (memo or "").strip()
    parts = [s.strip() for s in memo.split(" - ")]
    if re.match(r"(?i)\s*(transfer|pix|ted|doc)", memo) and len(parts) >= 2 and parts[1]:
        desc, low = parts[0], parts[0].lower()
        if "pix" in low and "enviad" in low: desc = "enviado via PIX"
        elif "pix" in low and "recebid" in low: desc = "recebido via PIX"
        return desc, parts[1]
    return memo, None

def parse(text):
    txns = []
    for blk in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.S | re.I):
        def g(tag):
            m = re.search(r"<" + tag + r">\s*([^<\r\n]+)", blk, re.I)
            return m.group(1).strip() if m else ""
        raw = re.sub(r"\D", "", g("DTPOSTED"))             # YYYYMMDDHHMMSS (fuso ignorado)
        dt = raw[:8]; tm = raw[8:14]
        amt = g("TRNAMT"); fitid = g("FITID")
        memo = g("MEMO") or g("NAME")
        if not amt or len(dt) < 8:
            continue
        try:
            cents = int(round(float(amt.replace(".", "").replace(",", ".") if amt.count(",") == 1 else amt) * 100))
        except Exception:
            continue
        desc, fav = _split_memo(memo)
        txns.append({"date": f"{dt[0:4]}-{dt[4:6]}-{dt[6:8]}",
                     "time": (f"{tm[0:2]}:{tm[2:4]}" if len(tm) >= 4 else None), "cents": cents,
                     "memo": memo[:200], "description": desc[:120], "favorecido": fav,
                     "fitid": fitid or None})
    return txns

def parse_account(text):
    """dados da conta a partir de <BANKACCTFROM> (conta) ou <CCACCTFROM> (cartão de crédito); None se ausente."""
    cc = False
    m = re.search(r"<BANKACCTFROM>(.*?)</BANKACCTFROM>", text, re.S | re.I)
    if not m:
        m = re.search(r"<CCACCTFROM>(.*?)</CCACCTFROM>", text, re.S | re.I); cc = True
    if not m: return None
    blk = m.group(1)
    def g(tag):
        mm = re.search(r"<" + tag + r">\s*([^<\r\n]+)", blk, re.I)
        return mm.group(1).strip() if mm else ""
    acctid = g("ACCTID")
    if not acctid: return None
    return {"bankid": g("BANKID"), "acctid": acctid,
            "accttype": ("CREDITCARD" if cc else g("ACCTTYPE")), "is_cc": cc}

def ensure_account(con, account):
    """acha (ou cria) a conta pelo número; retorna o id. Cartão de crédito vira conta tipo 'cartão de crédito'."""
    acctid = account["acctid"]
    row = con.execute("SELECT id FROM accounts WHERE numero=?", (acctid,)).fetchone()
    if row: return row[0]
    bankid = (account.get("bankid") or "").lstrip("0")
    bank = BANK_NAMES.get(bankid, f"Banco {account.get('bankid')}" if account.get("bankid") else "")
    if account.get("is_cc"):
        typ = "cartão de crédito"
        name = ("Cartão " + (bank + " " if bank else "") + acctid).strip()
    else:
        typ = "corrente" if (account.get("accttype") or "").upper() == "CHECKING" else "conta"
        name = f"{bank} {acctid}".strip()
    con.execute("INSERT OR IGNORE INTO accounts(name,type,bank,numero) VALUES(?,?,?,?)", (name, typ, bank or None, acctid))
    con.commit()
    row = con.execute("SELECT id FROM accounts WHERE numero=?", (acctid,)).fetchone()
    return row[0] if row else None

def reconcile(con, txns, account=None):
    """Concilia transações OFX. dedupe por FITID; match por valor+data ±2 dias -> conciliado;
    sem par -> importado. Se vier 'account', cria/usa a conta e preenche account_id.
    Retorna (conciliadas, novas, duplicadas)."""
    import finance_rules
    acc_id = ensure_account(con, account) if account and account.get("acctid") else None
    matched = imported = dup = 0
    for t in txns:
        if t["fitid"] and con.execute("SELECT 1 FROM transactions WHERE external_id=?", (t["fitid"],)).fetchone():
            dup += 1; continue
        cand = con.execute(
            """SELECT id FROM transactions WHERE amount=? AND source<>'ofx' AND external_id IS NULL
               AND ABS(julianday(date)-julianday(?))<=2
               ORDER BY ABS(julianday(date)-julianday(?)) LIMIT 1""",
            (t["cents"], t["date"], t["date"])).fetchone()
        if cand:
            con.execute("""UPDATE transactions SET status='conciliado', external_id=?,
                           account_id=COALESCE(account_id,?), favorecido=COALESCE(favorecido,?) WHERE id=?""",
                        (t["fitid"], acc_id, t.get("favorecido"), cand[0]))
            matched += 1
        else:
            cat = finance_rules.classify(con, t.get("favorecido"), t.get("description"), None)
            memo_u = (t.get("memo") or "").upper()
            if t["cents"] > 0 and t.get("description") == "recebido via PIX" and ("BCO DO BRASIL" in memo_u or "BANCO DO BRASIL" in memo_u):
                cat = "Receitas"   # Pix recebido do Banco do Brasil = receita (renda entrando)
            con.execute("""INSERT INTO transactions(date,time,amount,description,favorecido,category,account_id,source,status,external_id,notes)
                           VALUES(?,?,?,?,?,?,?,'ofx','importado',?,?)""",
                        (t["date"], t.get("time"), t["cents"], t.get("description"), t.get("favorecido"), cat, acc_id, t["fitid"], t.get("memo")))
            imported += 1
    con.commit()
    return matched, imported, dup

if __name__ == "__main__":
    import sys, json
    raw = decode_ofx(open(sys.argv[1], "rb").read())
    print(json.dumps({"account": parse_account(raw), "txns": parse(raw)}, ensure_ascii=False, indent=2))
