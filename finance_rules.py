#!/usr/bin/env python3
"""finance_rules.py — classificação de transações.
Ordem: (1) regras explícitas (tabela rules: campo favorecido/description/merchant/qualquer
contém um padrão -> categoria); (2) fallback por palavras-chave (categories.rule_keywords).
Match é case- e acento-insensível (substring)."""
import os, sys, json, sqlite3, unicodedata
ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("FINANCE_DB", os.path.join(ROOT, "finance.db"))

def deburr(s):
    return "".join(c for c in unicodedata.normalize("NFD", (s or "")) if unicodedata.category(c) != "Mn").lower().strip()

def _rule_cat(con, fav, desc, merchant):
    fields = {"favorecido": fav or "", "description": desc or "", "merchant": merchant or ""}
    allt = " ".join(fields.values())
    for field, pattern, category in con.execute("SELECT field,pattern,category FROM rules ORDER BY id"):
        p = deburr(pattern)
        if not p: continue
        target = allt if (field or "") in ("qualquer", "any", "") else fields.get(field, "")
        if p in deburr(target):
            return category
    return None

def _keyword_cat(con, fav, desc, merchant):
    txt = deburr(" ".join([fav or "", desc or "", merchant or ""]))
    for name, kws in con.execute("SELECT name,rule_keywords FROM categories WHERE rule_keywords IS NOT NULL AND rule_keywords<>'[]'"):
        try: arr = json.loads(kws)
        except Exception: arr = []
        for kw in arr:
            if kw and deburr(kw) in txt:
                return name
    return None

def classify(con, fav, desc, merchant):
    """categoria final (regra explícita tem prioridade; depois palavra-chave); None se nada casar."""
    return _rule_cat(con, fav, desc, merchant) or _keyword_cat(con, fav, desc, merchant)

def apply_rules(con):
    """reaplica SÓ as regras explícitas às transações existentes (sobrescreve quando uma regra casa). Retorna nº alterado."""
    n = 0
    for tid, fav, desc, merch, cat in con.execute(
            "SELECT id,favorecido,description,merchant,category FROM transactions").fetchall():
        m = _rule_cat(con, fav, desc, merch)
        if m and m != cat:
            con.execute("UPDATE transactions SET category=? WHERE id=?", (m, tid)); n += 1
    con.commit()
    return n

if __name__ == "__main__":
    con = sqlite3.connect(DB)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "classify":
        a = sys.argv
        print(classify(con, a[2] if len(a) > 2 else "", a[3] if len(a) > 3 else "", a[4] if len(a) > 4 else "") or "")
    elif cmd == "apply":
        print(apply_rules(con))
    con.close()
