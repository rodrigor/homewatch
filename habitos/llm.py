#!/usr/bin/env python3
"""llm.py — a única porta de entrada para o Claude CLI no sistema de hábitos.

Existe por causa de um bug que derrubou o coach velho por sete semanas: quando o
login expira, o CLI escreve o erro no STDOUT e sai com status 0. Quem só olhava
`$?` (ou só descartava o stderr) mandava "Failed to authenticate. API Error: 401"
para o Telegram como se fosse a mensagem do coach.

Regras aqui: toda saída é checada contra os padrões de erro de auth; a falha é
marcada no mesmo arquivo que o service_health.sh já vigia; e quem chama SEMPRE
recebe (texto, erro) — nunca um erro disfarçado de resposta.
"""
import json, os, re, subprocess, time

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)
ESTADO = os.path.join(RAIZ, "state")
CLI = "/usr/local/bin/claude"

# Mesmos padrões do claude_auth.sh (mantidos em sincronia de propósito).
PADROES_AUTH = re.compile(
    r"Failed to authenticate|OAuth access token has expired|OAuth token has expired|"
    r"Re-authenticate to continue|Invalid API key|API Error: 401|Please run /login",
    re.I)
# Erro de auth é sempre uma linha curta; texto longo é resposta legítima
# (o próprio Rodrigo pode perguntar ao PIrrai *sobre* esse erro).
MAX_LEN_ERRO = 400


def _marcador(escopo="rodrigor"):
    return os.path.join(ESTADO, f"claude_auth_error_{escopo}")


def e_erro_auth(txt):
    return bool(txt) and len(txt) <= MAX_LEN_ERRO and bool(PADROES_AUTH.search(txt))


def marcar_falha(origem, escopo="rodrigor"):
    """Mesmo formato do claude_auth.sh: primeiro|agora|origem (preserva o 1º)."""
    fp = _marcador(escopo)
    agora = str(int(time.time()))
    primeiro = agora
    if os.path.exists(fp):
        try:
            primeiro = open(fp).read().split("|")[0] or agora
        except OSError:
            pass
    os.makedirs(ESTADO, exist_ok=True)
    open(fp, "w").write(f"{primeiro}|{agora}|{origem}\n")


def marcar_ok(escopo="rodrigor"):
    try:
        os.remove(_marcador())
    except OSError:
        pass


def perguntar(prompt, modelo="sonnet", timeout=120, origem="habitos", cwd=None):
    """-> (texto, erro). Nunca levanta: quem chama decide o fallback."""
    if not os.path.exists(CLI):
        return None, f"claude CLI não encontrado em {CLI}"
    try:
        p = subprocess.run([CLI, "-p", "--model", modelo],
                           input=prompt, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd or RAIZ)
    except subprocess.TimeoutExpired:
        return None, f"timeout de {timeout}s"
    except Exception as e:                                  # noqa: BLE001
        return None, str(e)
    saida = (p.stdout or "").strip()
    if e_erro_auth(saida) or e_erro_auth((p.stderr or "").strip()):
        marcar_falha(origem)
        return None, "login do Claude expirou (marcado para o service_health)"
    if not saida:
        return None, (p.stderr or "resposta vazia").strip()[:200]
    marcar_ok()
    return saida, None


def perguntar_json(prompt, obrigatorios=(), modelo="sonnet", timeout=180,
                   origem="habitos", tentativas=2):
    """Igual, mas exige JSON com as chaves obrigatórias. Saída de LLM que vai
    TOCAR ESTADO passa por aqui: o sistema velho fazia grep '{.*}' e, quando não
    casava, seguia em silêncio como se nada tivesse acontecido."""
    ultimo = None
    for i in range(tentativas):
        txt, err = perguntar(prompt if i == 0 else
                             prompt + "\n\nResponda APENAS o JSON pedido, nada mais.",
                             modelo, timeout, origem)
        if err:
            return None, err
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            ultimo = "resposta sem JSON"
            continue
        try:
            dados = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            ultimo = f"JSON inválido: {e}"
            continue
        faltam = [k for k in obrigatorios if k not in dados]
        if faltam:
            ultimo = f"JSON sem as chaves {faltam}"
            continue
        return dados, None
    return None, ultimo or "falha ao obter JSON"
