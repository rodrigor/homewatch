#!/usr/bin/env python3
"""ofx_parser.py — parser tolerante de OFX (SGML dos bancos BR e OFX 2.x/XML).
Extrai transações: date (YYYY-MM-DD), cents (INTEGER, com sinal), memo, fitid."""
import re

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

if __name__ == "__main__":
    import sys, json
    print(json.dumps(parse(open(sys.argv[1], encoding="latin-1", errors="replace").read()), ensure_ascii=False, indent=2))
