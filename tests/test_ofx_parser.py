"""Testes do ofx_parser: decode, split de memo, parse SGML, conta e conciliação."""
import os, sys, sqlite3, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ofx_parser

SAMPLE = """OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<BANKACCTFROM>
<BANKID>0260
<ACCTID>12345-6
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260615120000[-3:BRT]
<TRNAMT>-45.90
<FITID>abc123
<MEMO>Compra no debito - PADARIA PAO QUENTE
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260616
<TRNAMT>1500.00
<FITID>xyz789
<MEMO>Transferencia Recebida - FULANO DE TAL - 123.456 - BCO XYZ
</STMTTRN>
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""

SCHEMA = """
CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, bank TEXT, numero TEXT);
CREATE TABLE transactions(id INTEGER PRIMARY KEY, date TEXT, time TEXT, amount INTEGER,
  description TEXT, merchant TEXT, favorecido TEXT, category TEXT, account_id INTEGER,
  source TEXT, status TEXT, external_id TEXT, notes TEXT,
  email_hint_category TEXT, email_hint_nivel INTEGER);
CREATE TABLE rules(id INTEGER PRIMARY KEY, field TEXT, pattern TEXT, category TEXT,
  amt_min INTEGER, amt_max INTEGER, dom INTEGER, dom_min INTEGER, dom_max INTEGER,
  account_id INTEGER, set_fav TEXT);
CREATE TABLE categories(name TEXT PRIMARY KEY, icon TEXT, grupo TEXT,
  is_transfer INTEGER, nivel INTEGER, rule_keywords TEXT);
"""


class TestDecode(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(ofx_parser.decode_ofx("Padaria Pão".encode("utf-8")), "Padaria Pão")

    def test_latin1_fallback(self):
        self.assertEqual(ofx_parser.decode_ofx("Padaria Pão".encode("latin-1")), "Padaria Pão")


class TestSplitMemo(unittest.TestCase):
    def test_compra_simples_nao_separa(self):
        d, f = ofx_parser._split_memo("Compra no debito - PADARIA")
        self.assertEqual(d, "Compra no debito - PADARIA")
        self.assertIsNone(f)

    def test_transferencia_extrai_favorecido(self):
        d, f = ofx_parser._split_memo("Transferência Recebida - FULANO DE TAL - 123 - BCO X")
        self.assertEqual(d, "Transferência Recebida")
        self.assertEqual(f, "FULANO DE TAL")

    def test_pix_enviado(self):
        d, f = ofx_parser._split_memo("Pix enviado - MERCADO DA ESQUINA - 99.888")
        self.assertEqual(d, "enviado via PIX")
        self.assertEqual(f, "MERCADO DA ESQUINA")

    def test_pix_recebido(self):
        d, f = ofx_parser._split_memo("Pix recebido - JOAO - BCO DO BRASIL")
        self.assertEqual(d, "recebido via PIX")
        self.assertEqual(f, "JOAO")


class TestParse(unittest.TestCase):
    def setUp(self):
        self.txns = ofx_parser.parse(SAMPLE)

    def test_quantidade(self):
        self.assertEqual(len(self.txns), 2)

    def test_debito(self):
        t = self.txns[0]
        self.assertEqual(t["date"], "2026-06-15")
        self.assertEqual(t["time"], "12:00")
        self.assertEqual(t["cents"], -4590)
        self.assertEqual(t["fitid"], "abc123")
        self.assertIsNone(t["favorecido"])

    def test_credito_com_favorecido(self):
        t = self.txns[1]
        self.assertEqual(t["date"], "2026-06-16")
        self.assertEqual(t["cents"], 150000)
        self.assertEqual(t["favorecido"], "FULANO DE TAL")

    def test_valor_com_virgula_br(self):
        txt = "<STMTTRN><DTPOSTED>20260101<TRNAMT>1.234,56<FITID>x</STMTTRN>"
        self.assertEqual(ofx_parser.parse(txt)[0]["cents"], 123456)


class TestParseAccount(unittest.TestCase):
    def test_bankacct(self):
        a = ofx_parser.parse_account(SAMPLE)
        self.assertEqual(a["acctid"], "12345-6")
        self.assertEqual(a["bankid"], "0260")
        self.assertEqual(a["accttype"], "CHECKING")
        self.assertFalse(a["is_cc"])

    def test_ccacct(self):
        a = ofx_parser.parse_account("<CCACCTFROM><ACCTID>9999</CCACCTFROM>")
        self.assertEqual(a["acctid"], "9999")
        self.assertTrue(a["is_cc"])
        self.assertEqual(a["accttype"], "CREDITCARD")

    def test_ausente(self):
        self.assertIsNone(ofx_parser.parse_account("<OFX></OFX>"))


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(SCHEMA)

    def tearDown(self):
        self.con.close()

    def test_ensure_account_nubank(self):
        aid = ofx_parser.ensure_account(self.con, {"bankid": "0260", "acctid": "12345-6",
                                                   "accttype": "CHECKING", "is_cc": False})
        row = self.con.execute("SELECT name, bank, type FROM accounts WHERE id=?", (aid,)).fetchone()
        self.assertEqual(row[1], "Nubank")
        self.assertEqual(row[2], "corrente")

    def test_match_importa_e_dedupe(self):
        # lançamento manual próximo (±2 dias, mesmo valor) deve conciliar
        self.con.execute("INSERT INTO transactions(date,amount,source,status) VALUES('2026-06-14',-4590,'manual','confirmado')")
        txns = ofx_parser.parse(SAMPLE)
        acc = ofx_parser.parse_account(SAMPLE)
        matched, imported, dup = ofx_parser.reconcile(self.con, txns, acc)
        self.assertEqual((matched, imported, dup), (1, 1, 0))
        st = self.con.execute("SELECT status, external_id FROM transactions WHERE amount=-4590").fetchone()
        self.assertEqual(st[0], "conciliado")
        self.assertEqual(st[1], "abc123")
        # reimportar o mesmo arquivo: tudo duplicado por FITID
        matched, imported, dup = ofx_parser.reconcile(self.con, txns, acc)
        self.assertEqual((matched, imported, dup), (0, 0, 2))

    def test_pix_bb_vira_receita(self):
        txt = "<STMTTRN><DTPOSTED>20260620<TRNAMT>2000.00<FITID>bb1<MEMO>Pix recebido - JOAO - BCO DO BRASIL</MEMO></STMTTRN>"
        ofx_parser.reconcile(self.con, ofx_parser.parse(txt), None)
        cat = self.con.execute("SELECT category FROM transactions WHERE external_id='bb1'").fetchone()[0]
        self.assertEqual(cat, "Receitas")


if __name__ == "__main__":
    unittest.main()
