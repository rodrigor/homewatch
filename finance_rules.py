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

_COLS_OK = False
def _ensure_rule_cols(con):
    """migração idempotente: faixa de dias (dom_min/dom_max), escopo por conta (account_id)
    e favorecido a atribuir (set_fav)."""
    global _COLS_OK
    if _COLS_OK: return
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(rules)")]
        for cn, ct in (("dom_min", "INTEGER"), ("dom_max", "INTEGER"), ("account_id", "INTEGER"), ("set_fav", "TEXT")):
            if cn not in cols: con.execute(f"ALTER TABLE rules ADD COLUMN {cn} {ct}")
        con.commit()
    except Exception:
        pass
    _COLS_OK = True

def _rule_match(con, fav, desc, merchant, amount=None, day=None, account_id=None):
    """retorna (categoria, set_fav) da regra mais específica que casa, ou (None, None).
    Casa por texto (favorecido/description/merchant/qualquer) e, opcionalmente, por VALOR
    (amt_min/amt_max em centavos abs), CONTA (account_id) e DIA do mês — dia exato (dom) OU
    faixa dom_min..dom_max (a faixa absorve fim de semana / próximo dia útil / deriva de ciclo).
    Vence a regra com maior score (mais restrições / texto mais longo)."""
    _ensure_rule_cols(con)
    fields = {"favorecido": fav or "", "description": desc or "", "merchant": merchant or ""}
    allt = " ".join(fields.values())
    av = abs(amount) if amount is not None else None
    best, best_fav, best_score = None, None, -1
    for field, pattern, category, amin, amax, dom, dmin, dmax, racct, sfav in con.execute(
            "SELECT field,pattern,category,amt_min,amt_max,dom,dom_min,dom_max,account_id,set_fav FROM rules ORDER BY id"):
        score = 0; restr = False
        p = deburr(pattern or "")
        if p:
            target = allt if (field or "") in ("qualquer", "any", "") else fields.get(field, "")
            if p not in deburr(target): continue
            score += len(p); restr = True
        if amin is not None or amax is not None:        # restrição por valor
            if av is None: continue
            if amin is not None and av < amin: continue
            if amax is not None and av > amax: continue
            score += 100; restr = True
        if racct is not None:                            # escopo por conta
            if account_id is None or int(account_id) != int(racct): continue
            score += 50; restr = True
        if dmin is not None or dmax is not None:          # faixa de dias
            if day is None: continue
            d = int(day)
            if dmin is not None and d < int(dmin): continue
            if dmax is not None and d > int(dmax): continue
            score += 80; restr = True
        elif dom is not None:                             # dia exato
            if day is None or int(day) != int(dom): continue
            score += 100; restr = True
        if restr and score > best_score:
            best, best_fav, best_score = category, sfav, score
    return best, best_fav

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

def classify(con, fav, desc, merchant, amount=None, day=None, account_id=None):
    """categoria final (regra explícita tem prioridade; depois palavra-chave); None se nada casar."""
    cat, _ = _rule_match(con, fav, desc, merchant, amount, day, account_id)
    return cat or _keyword_cat(con, fav, desc, merchant)

def classify_full(con, fav, desc, merchant, amount=None, day=None, account_id=None):
    """(categoria, set_fav): categoria cai p/ palavra-chave; set_fav só vem de regra explícita."""
    cat, sfav = _rule_match(con, fav, desc, merchant, amount, day, account_id)
    return (cat or _keyword_cat(con, fav, desc, merchant)), sfav

def apply_rules(con):
    """reaplica as regras explícitas às transações existentes: sobrescreve a categoria quando casa
    e preenche o favorecido (via set_fav) só quando estiver vazio. Retorna nº de transações alteradas.
    Transações com email_hint_category têm a categoria preservada (precedência do e-mail)."""
    n = 0
    for tid, fav, desc, merch, date, amount, acct, cat, hint_cat in con.execute(
            "SELECT id,favorecido,description,merchant,date,amount,account_id,category,email_hint_category FROM transactions").fetchall():
        m, sfav = _rule_match(con, fav, desc, merch, amount, _day(date), acct)
        sets, params = [], []
        # não sobrescreve categoria de transações com hint do e-mail
        if m and m != cat and not hint_cat: sets.append("category=?"); params.append(m)
        if m and sfav and not (fav or "").strip(): sets.append("favorecido=?"); params.append(sfav)
        if sets:
            params.append(tid)
            con.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id=?", params); n += 1
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
    for tid, fav, desc, cat, hint_cat in con.execute(
            "SELECT id,favorecido,description,category,email_hint_category FROM transactions").fetchall():
        text = deburr((fav or "") + " " + (desc or ""))
        for nome, cat_padrao, pats in prepared:
            if any(p in text for p in pats):
                sets, params = [], []
                if (fav or "") != nome: sets.append("favorecido=?"); params.append(nome)
                # não sobrescreve categoria de transações com hint do e-mail
                if cat_padrao and cat != cat_padrao and not hint_cat: sets.append("category=?"); params.append(cat_padrao)
                if sets:
                    params.append(tid)
                    con.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id=?", params); n += 1
                break
    con.commit()
    return n

def classify_all(con):
    """preenche categoria das transações SEM categoria (regras + palavras-chave) e o favorecido
    (via set_fav) quando vazio. Não sobrescreve categoria existente. Retorna nº preenchido."""
    n = 0
    for tid, fav, desc, merch, date, amount, acct in con.execute(
            "SELECT id,favorecido,description,merchant,date,amount,account_id FROM transactions WHERE category IS NULL OR category=''").fetchall():
        m, sfav = classify_full(con, fav, desc, merch, amount, _day(date), acct)
        sets, params = [], []
        if m: sets.append("category=?"); params.append(m)
        if sfav and not (fav or "").strip(): sets.append("favorecido=?"); params.append(sfav)
        if sets:
            params.append(tid)
            con.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id=?", params); n += 1
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
