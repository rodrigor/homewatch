#!/usr/bin/env python3
"""perguntas.py — pergunta de sim/não respondida por reação (👍/👎) no Telegram.

Reagir é o canal de menor atrito que existe: um toque, sem teclado, sem abrir a
conversa. Vale a pena para tudo que é binário — "aconteceu?", "posso aplicar?".

A resposta executa uma AÇÃO DECLARADA no momento da pergunta, de uma lista
fechada. Nada de comando arbitrário guardado à espera de um clique: o que a
reação pode disparar é o mesmo conjunto de primitivas que o resto do sistema já
conhece.

Uso:
  perguntas.py registrar <msg_id> <habito> --texto "..." --sim '{"tipo":"sessao"}'
                                                        --nao '{"tipo":"falha"}'
  perguntas.py resolver <msg_id> <sim|nao>      -> texto de confirmação (ou vazio)
  perguntas.py listar
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)
sys.path.insert(0, DIR)
import registro as R

ARQUIVO = os.path.join(RAIZ, "state", "habitos_perguntas.json")
VALIDADE_DIAS = 14
TIPOS = {"sessao", "falha", "nota", "aplicar_proposta", "pausar", "nada"}


def carregar():
    try:
        return json.load(open(ARQUIVO))
    except (OSError, json.JSONDecodeError):
        return {}


def salvar(d):
    limite = (datetime.now() - timedelta(days=VALIDADE_DIAS)).strftime("%Y-%m-%d")
    d = {k: v for k, v in d.items() if v.get("data", "9999") >= limite}
    os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
    tmp = ARQUIVO + ".tmp"
    json.dump(d, open(tmp, "w"), ensure_ascii=False, indent=2)
    os.replace(tmp, ARQUIVO)


def valida_acao(acao):
    if not acao:
        return {"tipo": "nada"}
    if acao.get("tipo") not in TIPOS:
        sys.exit(f"ação desconhecida: {acao.get('tipo')} (use {sorted(TIPOS)})")
    return acao


def registrar(msg_id, habito, texto, sim, nao):
    d = carregar()
    d[str(msg_id)] = {"habito": habito, "texto": texto, "data": R.hoje(),
                      "sim": valida_acao(sim), "nao": valida_acao(nao)}
    salvar(d)
    return {"registrada": msg_id}


def executar(con, habito, acao):
    tipo = acao.get("tipo")
    if tipo == "sessao":
        R.grava_evento(con, habito, "sessao", "reacao", R.hoje(),
                       {"nota": acao.get("texto", "confirmado por reação")})
        con.commit()
        return "✅ registrado."
    if tipo == "falha":
        R.grava_evento(con, habito, "falha", "reacao", R.hoje(),
                       {"obstaculo": acao.get("obstaculo", "nao_informado"),
                        "nota": acao.get("texto", "")})
        con.commit()
        return "ok, registrado que não rolou hoje."
    if tipo == "nota":
        R.grava_evento(con, habito, "nota", "reacao", R.hoje(),
                       {"texto": acao.get("texto", "")})
        con.commit()
        return "anotado."
    if tipo == "aplicar_proposta":
        p = subprocess.run([os.path.join(DIR, "coach.py"), "aplicar", habito],
                           capture_output=True, text=True, timeout=120)
        try:
            r = json.loads(p.stdout)
        except json.JSONDecodeError:
            return "não consegui aplicar a proposta — veja o log."
        return (f"✅ proposta aplicada (estratégia v{r['aplicada']})."
                if r.get("aplicada") else f"não apliquei: {r.get('erro')}")
    if tipo == "pausar":
        R.grava_evento(con, habito, "pausa_inicio", "reacao", R.hoje(),
                       {"ate": acao.get("ate"), "motivo": acao.get("motivo", "por reação")})
        con.commit()
        return "pausado. É só me avisar quando voltar."
    return acao.get("texto", "ok.")


def resolver(msg_id, resposta):
    d = carregar()
    p = d.get(str(msg_id))
    if not p:
        return None                      # não é pergunta minha: quem chamou que trate
    con = R.conectar()
    acao = p["sim"] if resposta == "sim" else p["nao"]
    texto = executar(con, p["habito"], acao)
    R.grava_evento(con, p["habito"], "resposta", "reacao", R.hoje(),
                   {"pergunta": p["texto"], "resposta": resposta,
                    "acao": acao, "message_id": msg_id})
    con.commit()
    d.pop(str(msg_id), None)
    salvar(d)
    return texto


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("registrar")
    sp.add_argument("msg_id"); sp.add_argument("habito")
    sp.add_argument("--texto", default=""); sp.add_argument("--sim"); sp.add_argument("--nao")
    sp = sub.add_parser("resolver")
    sp.add_argument("msg_id"); sp.add_argument("resposta", choices=["sim", "nao"])
    sub.add_parser("listar")
    a = ap.parse_args()
    if a.cmd == "registrar":
        print(json.dumps(registrar(a.msg_id, a.habito, a.texto,
                                   json.loads(a.sim) if a.sim else None,
                                   json.loads(a.nao) if a.nao else None)))
    elif a.cmd == "resolver":
        r = resolver(a.msg_id, a.resposta)
        if r is None:
            sys.exit(3)                  # sai 3 = "não era minha"
        print(r)
    else:
        print(json.dumps(carregar(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
