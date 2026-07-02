"""Testes dos helpers puros do web/finance/core.py (parse_cents, brl, money...)."""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "web", "finance"))
import core


class TestParseCents(unittest.TestCase):
    def test_virgula_decimal(self):
        self.assertEqual(core.parse_cents("45,90"), 4590)

    def test_negativo(self):
        self.assertEqual(core.parse_cents("-67,90"), -6790)

    def test_positivo_explicito(self):
        self.assertEqual(core.parse_cents("+10,00"), 1000)

    def test_com_simbolo_e_milhar(self):
        self.assertEqual(core.parse_cents("R$ 1.234,56"), 123456)

    def test_invalido(self):
        self.assertIsNone(core.parse_cents("abc"))
        self.assertIsNone(core.parse_cents(""))
        self.assertIsNone(core.parse_cents(None))


class TestFormat(unittest.TestCase):
    def test_brl(self):
        self.assertEqual(core.brl(123456), "R$ 1.234,56")
        self.assertEqual(core.brl(-500), "-R$ 5,00")

    def test_reais_plain(self):
        self.assertEqual(core.reais_plain(-6790), "-67,90")

    def test_money_usd(self):
        self.assertEqual(core.money(150000, "USD"), "US$ 1.500,00")

    def test_cursym(self):
        self.assertEqual(core.cursym("USD"), "US$")
        self.assertEqual(core.cursym(None), "R$")
        self.assertEqual(core.cursym("XYZ"), "XYZ")

    def test_roundtrip(self):
        # o que o brl imprime, o parse_cents lê de volta
        for cents in (0, 1, -1, 4590, -6790, 123456):
            self.assertEqual(core.parse_cents(core.brl(cents)), cents)


class TestTotByCurrency(unittest.TestCase):
    ROWS = [{"currency": "BRL", "amount": -100}, {"currency": None, "amount": -50},
            {"currency": "USD", "amount": 200}]

    def test_agrupa_por_moeda(self):
        self.assertEqual(core.tot_by_currency(self.ROWS), [("BRL", -150), ("USD", 200)])

    def test_val_label(self):
        self.assertEqual(core.val_label_for([]), "R$")
        self.assertEqual(core.val_label_for([{"currency": "USD", "amount": 1}]), "US$")
        self.assertEqual(core.val_label_for(self.ROWS), "moeda")


if __name__ == "__main__":
    unittest.main()
