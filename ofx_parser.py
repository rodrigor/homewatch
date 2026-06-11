#!/usr/bin/env python3
"""ofx_parser.py — parser tolerante de OFX (SGML dos bancos BR e OFX 2.x/XML).
Extrai transações: date (YYYY-MM-DD), cents (INTEGER, com sinal), memo, fitid."""
import re

def decode_ofx(b):
    """decodifica bytes de OFX tentando UTF-8 (Nubank) e caindo p/ latin-1 (bancos antigos)."""
    for enc in ("utf-8", "latin-1"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode("latin-1", "replace")

def parse(text):
    txns = []
    for blk in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.S | re.I):
        def g(tag):
            m = re.search(r"<" + tag + r">\s*([^<\r\n]+)", blk, re.I)
            return m.group(1).strip() if m else ""
        dt = re.sub(r"\D", "", g("DTPOSTED"))[:8]          # YYYYMMDD (ignora hora/fuso)
        amt = g("TRNAMT"); fitid = g("FITID")
        memo = g("MEMO") or g("NAME")
        if not amt or len(dt) < 8:
            continue
        try:
            cents = int(round(float(amt.replace(".", "").replace(",", ".") if amt.count(",") == 1 else amt) * 100))
        except Exception:
            continue
        txns.append({"date": f"{dt[0:4]}-{dt[4:6]}-{dt[6:8]}", "cents": cents,
                     "memo": memo[:120], "fitid": fitid or None})
    return txns

def reconcile(con, txns):
    """Concilia uma lista de transações OFX num conn sqlite aberto.
    - dedupe por FITID (external_id UNIQUE) -> extratos sobrepostos não duplicam
    - casa com transação existente (mesmo valor, data ±2 dias) -> status=conciliado
    - sem par -> insere como source=ofx, status=importado
    Retorna (conciliadas, novas, duplicadas)."""
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
            con.execute("UPDATE transactions SET status='conciliado', external_id=? WHERE id=?", (t["fitid"], cand[0]))
            matched += 1
        else:
            con.execute("""INSERT INTO transactions(date,amount,description,source,status,external_id)
                           VALUES(?,?,?,'ofx','importado',?)""", (t["date"], t["cents"], t["memo"], t["fitid"]))
            imported += 1
    con.commit()
    return matched, imported, dup

if __name__ == "__main__":
    import sys, json
    print(json.dumps(parse(open(sys.argv[1], encoding="latin-1", errors="replace").read()), ensure_ascii=False, indent=2))
