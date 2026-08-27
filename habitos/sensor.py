#!/usr/bin/env python3
"""sensor.py — texto livre vira métrica estruturada.

A pessoa escreve em prosa ("fiz 40 minutinhos, ficou puxado no fim"; "não deu,
tava viajando"). O registro precisa disso como campos e valores. Aqui é o único
lugar do sistema onde a LLM tem permissão de interpretar — e a saída dela é
validada contra a coleta declarada NA ESTRATÉGIA antes de virar linha no banco:
é a estratégia que diz quais campos existem, não este módulo.

Duas regras que vêm do sistema velho:
  - o que a pessoa NÃO disse não se inventa: campo ausente fica ausente;
  - ambiguidade não vira registro. Se não dá para afirmar que fez ou não fez, o
    sensor devolve uma PERGUNTA em vez de escrever no banco.

Uso:
  sensor.py interpretar <habito> "<texto>" [--data AAAA-MM-DD] [--aplicar]
"""
import argparse, json, os, sys
from datetime import date, datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import registro as R
import estrategia as E
import llm

OBRIGATORIOS = ("fez", "metricas", "confianca")


def campos_coleta(spec):
    linhas, obstaculos = [], []
    for c in spec.get("coleta", []):
        if c.get("quando") == "falha":
            obstaculos = c.get("valores", [])
            continue
        un = f" em {c['unidade']}" if c.get("unidade") else ""
        linhas.append(f"  - {c['campo']}: {c['tipo']}{un}"
                      f"{' (obrigatório se fez)' if c.get('obrigatorio') else ''}")
    return "\n".join(linhas), obstaculos


def interpretar(spec, texto, hoje=None):
    hoje = hoje or R.hoje()
    campos, obstaculos = campos_coleta(spec)
    prompt = f"""Você extrai dados de uma frase sobre o hábito "{spec.get('nome') or spec['habito']}".
Hoje é {hoje} ({['segunda','terça','quarta','quinta','sexta','sábado','domingo'][date.fromisoformat(hoje).weekday()]}).

FRASE: "{texto}"

Campos que podem ser extraídos (só estes):
{campos or '  (nenhum)'}
Obstáculos válidos (quando NÃO fez): {', '.join(obstaculos) or 'nenhum'}

Regras:
- fez: true se a pessoa diz que praticou, false se diz que NÃO praticou, null se não dá para saber.
- NÃO INVENTE número que a pessoa não disse. Campo não mencionado simplesmente não entra.
- data: converta referências relativas ("ontem", "segunda") para AAAA-MM-DD; se não houver, use {hoje}.
- confianca: 0..1. Use < 0.6 quando a frase for ambígua ou você tiver que adivinhar.
- pergunta: se confianca < 0.6, escreva a pergunta curta que resolveria a dúvida.

Responda SÓ um JSON:
{{"fez": true|false|null, "data": "AAAA-MM-DD", "metricas": {{"campo": valor}},
  "obstaculo": "<um dos válidos>"|null, "nota": "<resumo curto e legível>",
  "confianca": 0.0, "pergunta": "<pergunta ou vazio>"}}"""
    dados, err = llm.perguntar_json(prompt, OBRIGATORIOS, origem="sensor")
    if err:
        return None, err
    # a LLM não escolhe campo: só passa o que a estratégia declarou
    validos = {c["campo"] for c in spec.get("coleta", []) if c.get("quando") != "falha"}
    dados["metricas"] = {k: v for k, v in (dados.get("metricas") or {}).items()
                         if k in validos and isinstance(v, (int, float))}
    if dados.get("obstaculo") and dados["obstaculo"] not in obstaculos:
        dados["obstaculo"] = None
    try:
        date.fromisoformat(dados.get("data") or hoje)
    except ValueError:
        dados["data"] = hoje
    return dados, None


def aplicar(con, spec, dados, origem="telegram"):
    """Só escreve quando dá para afirmar. Ambiguidade vira pergunta, não registro."""
    habito = spec["habito"]
    if dados.get("fez") is None or float(dados.get("confianca", 0)) < 0.6:
        return {"registrado": False,
                "pergunta": dados.get("pergunta") or
                            "Não entendi se você fez ou não — pode confirmar?"}
    data = dados.get("data") or R.hoje()
    agreg = {c["campo"]: c.get("agregacao", "soma") for c in spec.get("coleta", [])}
    classe = {c["campo"]: c.get("classe", "resultado" if c.get("obrigatorio") else "contexto")
              for c in spec.get("coleta", [])}
    if dados["fez"]:
        eid = R.grava_evento(con, habito, "sessao", origem, data,
                             {"nota": dados.get("nota", ""), "texto_original": dados.get("_texto", "")})
        for campo, valor in dados["metricas"].items():
            un = next((c.get("unidade") for c in spec["coleta"] if c["campo"] == campo), None)
            R.grava_metrica(con, habito, campo, valor, un, classe.get(campo, "contexto"),
                            origem, data, eid, agregacao=agreg.get(campo, "soma"))
    else:
        eid = R.grava_evento(con, habito, "falha", origem, data,
                             {"obstaculo": dados.get("obstaculo") or "nao_informado",
                              "nota": dados.get("nota", "")})
    con.commit()
    return {"registrado": True, "evento": eid, "fez": dados["fez"], "data": data,
            "metricas": dados["metricas"], "obstaculo": dados.get("obstaculo")}


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("interpretar")
    sp.add_argument("habito"); sp.add_argument("texto")
    sp.add_argument("--data"); sp.add_argument("--aplicar", action="store_true")
    sp.add_argument("--origem", default="telegram")
    a = p.parse_args()
    spec = E.carregar(a.habito)
    dados, err = interpretar(spec, a.texto, a.data)
    if err:
        sys.exit(f"sensor: {err}")
    dados["_texto"] = a.texto
    saida = dict(dados)
    if a.aplicar:
        saida["resultado"] = aplicar(R.conectar(), spec, dados, a.origem)
    saida.pop("_texto", None)
    print(json.dumps(saida, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
