"""Testes do finance_rules: deburr, regras explícitas (texto/dia/conta/score) e keywords."""
import os, sys, sqlite3, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import finance_rules

SCHEMA = """
CREATE TABLE rules(id INTEGER PRIMARY KEY, field TEXT, pattern TEXT, category TEXT,
  amt_min INTEGER, amt_max INTEGER, dom INTEGER, dom_min INTEGER, dom_max INTEGER,
  account_id INTEGER, set_fav TEXT);
CREATE TABLE categories(name TEXT PRIMARY KEY, icon TEXT, grupo TEXT,
  is_transfer INTEGER, nivel INTEGER, rule_keywords TEXT);
CREATE TABLE transactions(id INTEGER PRIMARY KEY, date TEXT, time TEXT, amount INTEGER,
  description TEXT, merchant TEXT, favorecido TEXT, category TEXT, account_id INTEGER,
  source TEXT, status TEXT, external_id TEXT, notes TEXT,
  email_hint_category TEXT, email_hint_nivel INTEGER);
"""


def rule(con, **kw):
    cols = ", ".join(kw)
    con.execute(f"INSERT INTO rules({cols}) VALUES({','.join('?' * len(kw))})", list(kw.values()))


class TestDeburr(unittest.TestCase):
    def test_acentos_e_caixa(self):
        self.assertEqual(finance_rules.deburr("Café É Bom"), "cafe e bom")

    def test_none(self):
        self.assertEqual(finance_rules.deburr(None), "")


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(SCHEMA)

    def tearDown(self):
        self.con.close()

    def test_regra_explicita(self):
        rule(self.con, field="favorecido", pattern="energisa", category="Energia elétrica")
        self.assertEqual(finance_rules.classify(self.con, "ENERGISA PARAÍBA", "", None),
                         "Energia elétrica")

    def test_keyword_fallback(self):
        self.con.execute("INSERT INTO categories(name, rule_keywords) VALUES('Mercado', '[\"padaria\"]')")
        self.assertEqual(finance_rules.classify(self.con, None, "Padaria Pão Quente", None), "Mercado")

    def test_regra_vence_keyword(self):
        self.con.execute("INSERT INTO categories(name, rule_keywords) VALUES('Mercado', '[\"padaria\"]')")
        rule(self.con, field="description", pattern="padaria pao quente", category="Café da manhã")
        self.assertEqual(finance_rules.classify(self.con, None, "Padaria Pão Quente", None),
                         "Café da manhã")

    def test_faixa_de_dias(self):
        rule(self.con, field="description", pattern="debito em conta", category="Energia",
             dom_min=7, dom_max=13)
        self.assertEqual(finance_rules.classify(self.con, None, "Débito em conta Energisa", None, day=10),
                         "Energia")
        self.assertIsNone(finance_rules.classify(self.con, None, "Débito em conta Energisa", None, day=20))

    def test_escopo_por_conta(self):
        rule(self.con, field="description", pattern="mensalidade", category="Escola", account_id=2)
        self.assertIsNone(finance_rules.classify(self.con, None, "Mensalidade", None, account_id=1))
        self.assertEqual(finance_rules.classify(self.con, None, "Mensalidade", None, account_id=2), "Escola")

    def test_mais_restrita_vence(self):
        rule(self.con, field="description", pattern="uber", category="Transporte")
        rule(self.con, field="description", pattern="uber", category="Viagem", account_id=5)
        self.assertEqual(finance_rules.classify(self.con, None, "UBER TRIP", None, account_id=5), "Viagem")
        self.assertEqual(finance_rules.classify(self.con, None, "UBER TRIP", None, account_id=1), "Transporte")

    def test_classify_full_set_fav(self):
        rule(self.con, field="description", pattern="energisa", category="Energia", set_fav="Energisa")
        cat, sfav = finance_rules.classify_full(self.con, None, "ENERGISA PB", None)
        self.assertEqual((cat, sfav), ("Energia", "Energisa"))


class TestApply(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(SCHEMA)

    def tearDown(self):
        self.con.close()

    def test_classify_all_preenche_so_vazias(self):
        rule(self.con, field="description", pattern="uber", category="Transporte")
        self.con.execute("INSERT INTO transactions(date,amount,description) VALUES('2026-06-01',-1000,'UBER TRIP')")
        self.con.execute("INSERT INTO transactions(date,amount,description,category) VALUES('2026-06-02',-2000,'UBER TRIP','Viagem')")
        n = finance_rules.classify_all(self.con)
        self.assertEqual(n, 1)
        cats = [r[0] for r in self.con.execute("SELECT category FROM transactions ORDER BY id")]
        self.assertEqual(cats, ["Transporte", "Viagem"])

    def test_apply_rules_preserva_hint_email(self):
        rule(self.con, field="description", pattern="amazon", category="Compras")
        self.con.execute("""INSERT INTO transactions(date,amount,description,category,email_hint_category)
                            VALUES('2026-06-01',-5000,'AMAZON BR','Presentes','Presentes')""")
        n = finance_rules.apply_rules(self.con)
        self.assertEqual(n, 0)
        cat = self.con.execute("SELECT category FROM transactions").fetchone()[0]
        self.assertEqual(cat, "Presentes")


if __name__ == "__main__":
    unittest.main()
