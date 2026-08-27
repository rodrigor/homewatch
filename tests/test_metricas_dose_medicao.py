"""Dose e medição não se leem igual — e confundir as duas inverte o diagnóstico.

Regressão de dois bugs reais, achados só quando o coach rodou sobre dado de
verdade:

  1. dose (soma/media_dia): semana SEM registro é zero, não é dado faltando.
     Tratada como ausente, uma única semana boa em onze pontuava 100%.
  2. medição (ultimo): semana sem registro é desconhecida, e a semana EM CURSO
     conta — o peso de hoje é fato, não meia semana somada. Excluí-la descartava
     justamente a medição mais recente e o ritmo saía nulo.
"""
import os
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "habitos"))


class DoseVersusMedicao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        os.environ["HABITOS_DB"] = self.tmp.name
        for mod in ("registro", "coach", "estrategia"):
            sys.modules.pop(mod, None)
        import registro as R
        import coach as C
        self.R, self.C = R, C
        R.DB = self.tmp.name
        self.con = R.conectar()
        self.spec = {
            "habito": "t", "versao": 1, "estado": "ativo",
            "criterio_sucesso": {"adesao": {"metrica": "sessoes_semana", "min": 1}},
            "horizonte": {"dwell_min_semanas": 2},
            "gatilhos": [], "mensagens": {}, "gates": {},
            "coleta": [{"campo": "dose", "tipo": "numero", "agregacao": "soma"}],
            "medicoes": [{"campo": "marca", "agregacao": "ultimo"}],
        }

    def tearDown(self):
        os.unlink(self.tmp.name)
        os.environ.pop("HABITOS_DB", None)

    def semanas(self, n=4):
        return self.C.segundas("2026-06-08", "2026-06-29")[:n]

    def test_dose_sem_registro_conta_como_zero(self):
        """Uma semana boa em quatro é 25%, não 100%."""
        eid = self.R.grava_evento(self.con, "t", "sessao", "teste", "2026-06-15")
        self.R.grava_metrica(self.con, "t", "dose", 40, None, "resultado", "teste",
                             "2026-06-15", eid, agregacao="soma")
        self.con.commit()
        r = self.C.avaliar_metrica(self.con, self.spec, self.semanas(),
                                   {"metrica": "dose", "min": 30})
        self.assertEqual([x["valor"] for x in r["serie"]], [0.0, 40.0, 0.0, 0.0])
        self.assertAlmostEqual(r["nota"], 0.25)

    def test_medicao_ausente_nao_vira_zero(self):
        """Semana sem pesagem é desconhecida — não é 'zero quilos'."""
        for data, valor in [("2026-06-08", 87.5), ("2026-06-29", 88.3)]:
            self.R.grava_metrica(self.con, "t", "marca", valor, "kg", "resultado",
                                 "teste", data, agregacao="ultimo")
        self.con.commit()
        r = self.C.avaliar_metrica(self.con, self.spec, self.semanas(),
                                   {"metrica": "marca", "direcao": "descer"})
        self.assertEqual([x["valor"] for x in r["serie"]], [87.5, None, None, 88.3])
        self.assertAlmostEqual(r["ritmo"], (88.3 - 87.5) / 3)
        self.assertEqual(r["nota"], 0.0)      # subiu, e o critério pedia descer

    def test_medicao_da_semana_em_curso_conta(self):
        """A medição mais recente não pode ser descartada por estar na semana atual."""
        self.R.grava_metrica(self.con, "t", "marca", 90.0, "kg", "resultado", "teste",
                             "2026-06-08", agregacao="ultimo")
        self.R.grava_metrica(self.con, "t", "marca", 89.0, "kg", "resultado", "teste",
                             "2026-07-06", agregacao="ultimo")
        self.con.commit()
        r = self.C.avaliar_metrica(self.con, self.spec, self.semanas(),
                                   {"metrica": "marca", "direcao": "descer"},
                                   semana_atual="2026-07-06")
        self.assertEqual(r["serie"][-1]["valor"], 89.0)
        self.assertLess(r["ritmo"], 0)
        self.assertEqual(r["nota"], 1.0)

    def test_dose_ignora_semana_em_curso(self):
        """Dose da semana pela metade não entra: julgaria semana inacabada."""
        r = self.C.avaliar_metrica(self.con, self.spec, self.semanas(),
                                   {"metrica": "dose", "min": 30},
                                   semana_atual="2026-07-06")
        self.assertEqual(len(r["serie"]), 4)


if __name__ == "__main__":
    unittest.main()
