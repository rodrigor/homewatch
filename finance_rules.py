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

def _rule_cat(con, fav, desc, merchant, amount=None, day=None):
    """casa por texto (favorecido/description/merchant) e, opcionalmente, por VALOR (amt_min/amt_max,
    em centavos absolutos) e DIA do mês (dom). Vence a regra mais específica (texto longo + restrições)."""
    fields = {"favorecido": fav or "", "description": desc or "", "merchant": merchant or ""}
    allt = " ".join(fields.values())
    av = abs(amount) if amount is not None else None
    best, best_score = None, -1
    for field, pattern, category, amin, amax, dom in con.execute(
            "SELECT field,pattern,category,amt_min,amt_max,dom FROM rules ORDER BY id"):
        score = 0
        p = deburr(pattern or "")
        if p:
            target = allt if (field or "") in ("qualquer", "any", "") else fields.get(field, "")
            if p not in deburr(target): continue
            score += len(p)
        if amin is not None or amax is not None:        # restrição por valor
            if av is None: continue
            if amin is not None and av < amin: continue
            if amax is not None and av > amax: continue
            score += 100
        if dom is not None:                              # restrição por dia do mês
            if day is None or int(day) != int(dom): continue
            score += 100
        if (p or amin is not None or amax is not None or dom is not None) and score > best_score:
            best, best_score = category, score
    return best

def _keyword_cat(con, fav, desc, merchant):
    txt = deburr(" ".join([fav or "", desc or "", merchant or ""]))
    for name, kws in con.execute("SELECT name,rule_keywords FROM categories WHERE rule_keywords IS NOT NULL AND rule_keywords<>'[]'"):
        try: arr = json.loads(kws)
        except Exception: arr = []
        for kw in arr:
            if kw and deburr(kw) in txt:
                return name
    return None

def _day(date):
    return int(date[8:10]) if date and len(date) >= 10 else None

def classify(con, fav, desc, merchant, amount=None, day=None):
    """categoria final (regra explícita tem prioridade; depois palavra-chave); None se nada casar."""
    return _rule_cat(con, fav, desc, merchant, amount, day) or _keyword_cat(con, fav, desc, merchant)

def apply_rules(con):
    """reaplica SÓ as regras explícitas às transações existentes (sobrescreve quando uma regra casa). Retorna nº alterado."""
    n = 0
    for tid, fav, desc, merch, date, amount, cat in con.execute(
            "SELECT id,favorecido,description,merchant,date,amount,category FROM transactions").fetchall():
        m = _rule_cat(con, fav, desc, merch, amount, _day(date))
        if m and m != cat:
            con.execute("UPDATE transactions SET category=? WHERE id=?", (m, tid)); n += 1
    con.commit()
    return n

def apply_favorecidos(con):
    """normaliza o favorecido pelos apelidos da entidade e aplica a categoria_padrao. Retorna nº alterado."""
    favs = con.execute("SELECT nome,categoria_padrao,aliases FROM favorecidos").fetchall()
    if not favs: return 0
    prepared = []
    for nome, cat_padrao, aliases_json in favs:
        try: aliases = json.loads(aliases_json or "[]")
        except Exception: aliases = []
        pats = [p for p in ([deburr(nome)] + [deburr(a) for a in (aliases or []) if a]) if p]
        prepared.append((nome, cat_padrao, pats))
    n = 0
    for tid, fav, desc, cat in con.execute("SELECT id,favorecido,description,category FROM transactions").fetchall():
        text = deburr((fav or "") + " " + (desc or ""))
        for nome, cat_padrao, pats in prepared:
            if any(p in text for p in pats):
                sets, params = [], []
                if (fav or "") != nome: sets.append("favorecido=?"); params.append(nome)
                if cat_padrao and cat != cat_padrao: sets.append("category=?"); params.append(cat_padrao)
                if sets:
                    params.append(tid)
                    con.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id=?", params); n += 1
                break
    con.commit()
    return n

def classify_all(con):
    """preenche a categoria das transações SEM categoria (regras + palavras-chave). Não sobrescreve. Retorna nº preenchido."""
    n = 0
    for tid, fav, desc, merch, date, amount in con.execute(
            "SELECT id,favorecido,description,merchant,date,amount FROM transactions WHERE category IS NULL OR category=''").fetchall():
        m = classify(con, fav, desc, merch, amount, _day(date))
        if m:
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
    elif cmd == "classifyall":
        print(classify_all(con))
    elif cmd == "favorecidos":
        print(apply_favorecidos(con))
    con.close()
