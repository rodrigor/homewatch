"""Bloqueio: o núcleo do sistema de hábitos não pode saber de domínio.

O sistema é genérico de propósito — hoje serve exercício físico, amanhã hábitos
de investimento e controle de orçamento. Todo vazamento começa inocente (um
`case "min") campo=minutos` na fachada, um `["minutos","fc_media"]` no
formulário) e termina com o núcleo sabendo de batimento cardíaco.

Se este teste falhar: o conhecimento não pertence ao núcleo. Ele vai para a
estratégia (dado, em habitos/estrategias/) ou para um módulo de domínio próprio.
Exceção deliberada e rara: marque a linha com `nucleo:ok` e o motivo.
"""
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "habitos"))
import lint_nucleo  # noqa: E402


class NucleoGenerico(unittest.TestCase):
    def test_sem_dominio_no_nucleo(self):
        achados = lint_nucleo.achados(RAIZ)
        if achados:
            linhas = "\n".join(f"  {a}:{l}  [{t}]\n      {txt}" for a, l, t, txt in achados)
            self.fail(f"domínio vazando para o núcleo ({len(achados)}):\n{linhas}")

    def test_o_bloqueio_pega_reincidencia(self):
        """O teste acima só vale se o detector realmente detectar."""
        self.assertTrue(lint_nucleo.ABSOLUTOS.search("calcula a zona 2 pelo bpm"))
        self.assertTrue(lint_nucleo.ABSOLUTOS.search("valor do aporte na carteira"))
        self.assertTrue(lint_nucleo.CTX.search('campos = ["minutos", "fc_media"]'))
        self.assertTrue(lint_nucleo.CTX.search("campo=minutos"))
        # prosa não pode dar falso positivo
        self.assertFalse(lint_nucleo.CTX.search("roda a cada 15 minutos"))
        self.assertFalse(lint_nucleo.ABSOLUTOS.search("registra a sessão do dia"))

    def test_isencao_exige_marcador(self):
        self.assertTrue(lint_nucleo.ISENCAO.search("x = 1  # nucleo:ok motivo"))
        self.assertFalse(lint_nucleo.ISENCAO.search("x = 1  # depois eu arrumo"))


if __name__ == "__main__":
    unittest.main()


class InteresseEmMetrica(unittest.TestCase):
    """Quem é estimulado por uma métrica sai da declaração, não de código."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RAIZ, "habitos"))
        import estrategia
        self.E = estrategia

    def spec(self, hid, campos_pessoa=(), campos_habito=(), resultado=None, secundario=None):
        return {
            "habito": hid, "estado": "ativo",
            "medicoes": [{"campo": c, "escopo": "pessoa"} for c in campos_pessoa],
            "coleta": [{"campo": c} for c in campos_habito],
            "criterio_sucesso": {"adesao": {"min": 1},
                                 "resultado": {"metrica": resultado} if resultado else None,
                                 "secundarios": ([{"metrica": secundario}] if secundario else [])},
        }

    def test_papel_do_campo(self):
        s = self.spec("h", campos_pessoa=["compartilhada"], campos_habito=["propria"],
                      resultado="propria", secundario="compartilhada")
        self.assertEqual(self.E.papel_do_campo(s, "propria"), "resultado")
        self.assertEqual(self.E.papel_do_campo(s, "compartilhada"), "secundario")
        self.assertIsNone(self.E.papel_do_campo(s, "inexistente"))

    def test_escopo_separa_quem_ve(self):
        s = self.spec("h", campos_pessoa=["compartilhada"], campos_habito=["propria"])
        self.assertEqual(self.E.campos_declarados(s),
                         {"compartilhada": "pessoa", "propria": "h"})
