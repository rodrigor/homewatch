"""Smoke test do web app de finanças: todas as rotas GET respondem 200 e o CSRF
bloqueia POST sem token. Roda contra uma CÓPIA do finance.db (via FINANCE_DB)."""
import os, sys, shutil, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIN = os.path.join(ROOT, "web", "finance")

_tmp = tempfile.mkdtemp(prefix="fin-smoke-")
_dbcopy = os.path.join(_tmp, "finance.db")
shutil.copy(os.path.join(ROOT, "finance.db"), _dbcopy)
os.environ["FINANCE_DB"] = _dbcopy

sys.path.insert(0, FIN)
sys.path.insert(0, ROOT)
# outro teste pode já ter importado core (com o DB real, via cache de módulo);
# força o DB da cópia ANTES do create_app do app.py rodar as migrações
import core
core.DB = _dbcopy
from app import app as application

GET_ROUTES = [
    "/financas", "/transacoes", "/transacoes/nova", "/favorecidos",
    "/favorecido?nome=Teste", "/favorecidos/gerir", "/regras", "/limites",
    "/contas", "/grupos", "/conciliacao", "/transferencia", "/investimentos",
    "/senha", "/api/cat_tx",
]


class TestSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        application.config["TESTING"] = True
        cls.client = application.test_client()
        with cls.client.session_transaction() as s:
            s["user"] = "smoke-test"; s["role"] = "editor"

    def test_login_publico(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)

    def test_raiz_redireciona(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)

    def test_rotas_logadas_200(self):
        for route in GET_ROUTES:
            with self.subTest(route=route):
                r = self.client.get(route)
                self.assertEqual(r.status_code, 200, f"{route} -> {r.status_code}")

    def test_sem_login_redireciona(self):
        anon = application.test_client()
        r = anon.get("/financas")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_csrf_bloqueia_post_sem_token(self):
        r = self.client.post("/api/tx/999999999/delete")
        self.assertEqual(r.status_code, 403)

    def test_csrf_aceita_post_com_token(self):
        with self.client.session_transaction() as s:
            s["_csrf"] = "tok-de-teste"
        r = self.client.post("/api/tx/999999999/delete", headers={"X-CSRF": "tok-de-teste"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
