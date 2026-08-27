#!/usr/bin/env python3
"""lint_nucleo.py — impede que conhecimento de DOMÍNIO entre no núcleo.

O sistema de hábitos tem três níveis:

  núcleo    eventos, métricas, gatilhos, quadrante, envelope, versionamento.
            Não sabe o que é um treino, uma página lida ou um copo de água.
  domínio   "FC entre 120-135 é Zona 2", "dose aeróbica move VO2". Mora na
            estratégia (dado) ou, em último caso, num módulo de domínio próprio.
  instância os números de uma pessoa, no arquivo da estratégia dela.

Todo vazamento do meio para o de cima começa inocente — um `case "min") campo=minutos`
na fachada, um `["minutos","fc_media"]` no formulário — e termina com o núcleo
sabendo de batimento cardíaco. Este teste é o bloqueio: falha o commit.

Exceção deliberada: escreva `nucleo:ok` num comentário na mesma linha, com o
motivo. Deve ser rara o bastante para doer.

Uso:  lint_nucleo.py [--listar]
"""
import os, re, sys

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)

# Arquivos que TÊM de permanecer genéricos.
NUCLEO = [
    "habitos/registro.py", "habitos/estrategia.py", "habitos/rotina.py",
    "habitos/sensor.py", "habitos/coach.py", "habitos/llm.py",
    "habitos/schema.sql", "habitos/envelope.json",
    "habitos.sh", "web/habitos/app.py",
]
# Fora da lista de propósito: habitos/migrar.py (script histórico, de uma
# migração específica) e habitos/estrategias/*.json (é onde o domínio deve morar).

# Termos que não existem fora de um domínio concreto.
ABSOLUTOS = re.compile(
    # (?<![\w]) e não \b: "minutos_zona2" tem underscore antes do termo, e o \b
    # não enxerga fronteira ali — foi assim que um comentário meu escapou
    # exercício / saúde
    r"(?<![a-zA-Z0-9])(vo2|bpm|zona ?2|treino|exerc[íi]ci|muscula[çc][ãa]o|hipertrofia|"
    r"ergom[ée]tric|hiit|imc|kcal|caloria|batimento|card[íi]aco|aer[óo]bic|"
    r"glicose|jejum|cigarro|medita[çc]|"
    # leitura / estudo
    r"cap[íi]tulo|livro|"
    # finanças, investimento e orçamento (hábitos que estão por vir)
    r"aporte|dividendo|carteira|ativo financeiro|renda fixa|renda vari[áa]vel|"
    r"or[çc]amento|aloca[çc][ãa]o|rentabilidade|corretora|patrim[ôo]nio|"
    r"cdi|ipca|selic|a[çc][õo]es|fii)", re.I)

# Termos que só acusam quando aparecem como CAMPO (entre aspas, ou em
# atribuição): "minutos" numa string é domínio; "a cada 15 minutos" é prosa.
CONTEXTUAIS = ["minutos", "fc_media", "distancia", "paginas", "passos", "peso", "km",
               "valor_aportado", "saldo", "gasto", "receita", "categoria"]
# quatro formas: "campo", campo:, campo=..., =campo (esta última era o furo — o
# vazamento original era `case "$un" in min) campo=minutos`, com o termo DEPOIS
# do sinal de igual)
CTX = re.compile(
    r"""(?:["'](?:%s)["']|\b(?:%s)\s*[:=]|\.(?:%s)\b|[:=]\s*(?:%s)\b)"""
    % tuple(["|".join(CONTEXTUAIS)] * 4), re.I)

ISENCAO = re.compile(r"nucleo:ok", re.I)


def achados(raiz=RAIZ):
    out = []
    for rel in NUCLEO:
        fp = os.path.join(raiz, rel)
        if not os.path.exists(fp):
            out.append((rel, 0, "ARQUIVO AUSENTE", ""))
            continue
        for i, linha in enumerate(open(fp, encoding="utf-8"), 1):
            if ISENCAO.search(linha):
                continue
            m = ABSOLUTOS.search(linha) or CTX.search(linha)
            if m:
                out.append((rel, i, m.group(0).strip(), linha.strip()[:100]))
    return out


def main():
    ruins = achados()
    if not ruins:
        print(f"núcleo limpo: {len(NUCLEO)} arquivos sem conhecimento de domínio")
        return 0
    print("DOMÍNIO VAZANDO PARA O NÚCLEO:\n", file=sys.stderr)
    for arq, ln, termo, texto in ruins:
        print(f"  {arq}:{ln}  [{termo}]\n      {texto}", file=sys.stderr)
    print(f"\n{len(ruins)} ocorrência(s). O núcleo não pode saber de domínio: mova para a\n"
          "estratégia (dado) ou para um módulo de domínio. Exceção real: 'nucleo:ok' na linha.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
