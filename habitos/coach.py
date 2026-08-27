#!/usr/bin/env python3
"""coach.py — avalia a estratégia corrente e propõe a próxima.

Divisão de trabalho, na ordem:
  1. DETERMINÍSTICO: adesão, resultado, obstáculos e silêncios saem de SQL, não
     de LLM. Números não são opinião.
  2. LLM: só diagnostica e propõe uma mudança, vendo o histórico do que já foi
     tentado (para não repetir alavanca queimada).
  3. ENVELOPE: a proposta é validada contra o que o coach pode mexer sozinho.
     Fora disso vira PROPOSTA pendente, que espera o "ok" de um humano.

O quadrante é o coração do diagnóstico e é o que o sistema velho não tinha:
                     resultado subindo | resultado parado
  adesão alta            ok/evoluir    | dose_insuficiente
  adesão baixa           ruido         | nao_cabe

Uso:
  coach.py avaliar <habito> [--em AAAA-MM-DD] [--dry-run] [--forcar]
  coach.py aplicar <habito>        # aplica a última proposta pendente
  coach.py simular <habito> [--de AAAA-MM-DD] [--com-llm]
"""
import argparse, json, os, subprocess, sys
from datetime import date, datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)
sys.path.insert(0, DIR)
import registro as R
import estrategia as E
import llm

ENVELOPE = json.load(open(os.path.join(DIR, "envelope.json")))
LIM = ENVELOPE["limites"]
TG = os.path.join(RAIZ, "tg_notify.sh")
DECISOES = ["manter", "level_up", "reduzir_meta", "mover_gatilho", "ajustar_mensagem",
            "declarar_resultado", "pedir_ajuda", "conversa_humana", "suspender"]


# ── 1. leitura determinística ────────────────────────────────────────────────
def segundas(de, ate):
    d = date.fromisoformat(de); a = date.fromisoformat(ate)
    d -= timedelta(days=d.weekday()); a -= timedelta(days=a.weekday())
    out = []
    while d <= a:
        out.append(d.isoformat()); d += timedelta(weeks=1)
    return out


def agregacao_de(spec, campo):
    for bloco in ("coleta", "medicoes", "derivadas"):
        for item in spec.get(bloco, []) or []:
            if item.get("campo") == campo:
                return item.get("agregacao", "soma")
    return "soma"


def avaliar_metrica(con, spec, semanas, criterio, semana_atual=None):
    """Nota 0..1.5 de UMA métrica na janela, conforme o critério declarado.
    Serve tanto para o resultado (que define o quadrante) quanto para as
    secundárias (que só informam).

    DOSE e MEDIÇÃO não se leem igual, e confundir as duas inverte o diagnóstico:
      - dose (soma/media_dia): semana sem registro é ZERO, não é dado faltando.
        Tratá-la como ausente faria "uma única semana boa em onze" pontuar 100%.
      - medição (ultimo/media): semana sem registro é DESCONHECIDA, e a semana em
        curso conta — o peso de hoje é fato, não meia semana somada.
    """
    vazio = {"nota": None, "serie": [], "ritmo": None}
    if not criterio or not semanas:
        return vazio
    campo = criterio["metrica"]
    esc = E.escopo_de(spec, campo)          # métrica da pessoa é lida fora do hábito
    dose = agregacao_de(spec, campo) in ("soma", "media_dia")
    janela = list(semanas)
    if not dose and semana_atual and semana_atual not in janela:
        janela.append(semana_atual)
    vals = {r["semana"]: r["valor"] for r in con.execute(
        "SELECT semana, valor FROM v_metricas_semanais WHERE escopo=? AND campo=?",
        (esc, campo))}
    serie = [{"semana": s, "valor": vals.get(s, 0.0 if dose else None)} for s in janela]
    medidos = [x for x in serie if x["valor"] is not None]
    nota, ritmo = None, None
    if criterio.get("direcao"):
        # Métrica com DIREÇÃO (a que precisa cair, ou subir, ao longo do
        # tempo): o que importa é o RITMO, não bater um limiar semanal. Sem
        # isto, uma meta declarada como "ficar abaixo de X" daria resultado
        # zero em toda semana até o dia em que a linha fosse cruzada — e o
        # coach leria meses de progresso real como fracasso.
        if len(medidos) >= 2:
            dv = medidos[-1]["valor"] - medidos[0]["valor"]
            dsem = max(1, (date.fromisoformat(medidos[-1]["semana"])
                           - date.fromisoformat(medidos[0]["semana"])).days / 7)
            ritmo = dv / dsem
            sinal = -1 if criterio["direcao"] == "descer" else 1
            alvo_taxa = criterio.get("taxa_semanal")
            if criterio["direcao"] == "manter":
                tol = criterio.get("tolerancia", abs(alvo_taxa or 0.5))
                nota = 1.0 if abs(ritmo) <= tol else max(0.0, tol / abs(ritmo))
            elif alvo_taxa:
                nota = max(0.0, min(1.5, (sinal * ritmo) / abs(alvo_taxa)))
            else:
                nota = 1.0 if sinal * ritmo > 0 else 0.0
    elif criterio.get("min") is not None:
        nota = sum(1 for x in medidos if x["valor"] >= criterio["min"]) / max(1, len(medidos))
    elif criterio.get("max") is not None:
        nota = sum(1 for x in medidos if x["valor"] <= criterio["max"]) / max(1, len(medidos))

    return {"nota": nota, "serie": serie, "ritmo": ritmo}


def medir(con, spec, ate=None, desde=None):
    """Adesão e resultado da janela da estratégia corrente. Semana em curso fica
    de fora: julgar semana pela metade é o jeito mais fácil de errar o diagnóstico."""
    habito = spec["habito"]
    ate = ate or R.hoje()
    linha = con.execute("""SELECT ativa_de FROM estrategias WHERE habito=? AND versao=?""",
                        (habito, spec["versao"])).fetchone()
    de = desde or (linha["ativa_de"] if linha else ate)
    hoje_seg = date.fromisoformat(ate) - timedelta(days=date.fromisoformat(ate).weekday())
    semanas = [s for s in segundas(de, ate) if s < hoje_seg.isoformat()]
    meta = float(spec["criterio_sucesso"]["adesao"]["min"])

    sess = {r["semana"]: r["sessoes"] for r in con.execute(
        "SELECT semana, sessoes FROM v_sessoes_semanais WHERE habito=?", (habito,))}
    por_semana = [{"semana": s, "sessoes": sess.get(s, 0),
                   "bateu": sess.get(s, 0) >= meta} for s in semanas]
    n = len(por_semana) or 1
    adesao = sum(1 for s in por_semana if s["bateu"]) / n

    res_spec = spec["criterio_sucesso"].get("resultado")
    atual = hoje_seg.isoformat()
    avaliada = avaliar_metrica(con, spec, semanas, res_spec, atual)
    resultado, serie_res, ritmo = avaliada["nota"], avaliada["serie"], avaliada["ritmo"]

    # SECUNDÁRIAS: acompanhadas e reportadas, mas NÃO entram no quadrante. Servem
    # para o caso em que o hábito contribui para um indicador sem ser a alavanca
    # principal dele — julgar a estratégia por esse indicador seria cobrar do
    # hábito errado.
    secundarios = []
    for sec in spec["criterio_sucesso"].get("secundarios", []) or []:
        a = avaliar_metrica(con, spec, semanas, sec, atual)
        secundarios.append({"metrica": sec["metrica"], "nota": a["nota"],
                            "ritmo_semanal": a["ritmo"], "serie": a["serie"],
                            "observacao": sec.get("nota", "")})

    obst = [dict(r) for r in con.execute(
        """SELECT obstaculo, SUM(n) n FROM v_obstaculos_semanais
           WHERE habito=? AND semana >= ? GROUP BY obstaculo ORDER BY n DESC""",
        (habito, semanas[0] if semanas else de))]
    silencios = con.execute(
        """SELECT COUNT(*) FROM v_eventos WHERE habito=? AND tipo='silencio' AND semana >= ?""",
        (habito, semanas[0] if semanas else de)).fetchone()[0]

    if adesao >= 0.8:
        quad = "ok" if (resultado is None or resultado >= 0.5) else "dose_insuficiente"
    else:
        quad = "nao_cabe" if (resultado is None or resultado < 0.5) else "ruido"
    return {"de": de, "ate": ate, "semanas": por_semana, "meta": meta,
            "adesao": round(adesao, 2),
            "resultado": None if resultado is None else round(resultado, 2),
            "ritmo_semanal": None if ritmo is None else round(ritmo, 3),
            "criterio_resultado": res_spec, "secundarios": secundarios,
            "resultado_declarado": bool(res_spec), "serie_resultado": serie_res,
            "obstaculos": obst, "silencios": silencios, "quadrante": quad,
            "semanas_avaliadas": len(por_semana)}


def historico_decisoes(con, habito, n=8):
    return [dict(r) for r in con.execute(
        """SELECT ts, versao, adesao, quadrante, decisao, aplicada, motivo
           FROM avaliacoes WHERE habito=? ORDER BY id DESC LIMIT ?""", (habito, n))]


def estrategias_falhadas(con, habito):
    """Teto de escalada: depois de N estratégias seguidas com desfecho de falha,
    parar de girar parâmetro e abrir uma conversa de verdade."""
    linhas = con.execute("""SELECT desfecho FROM estrategias WHERE habito=?
                            AND ativa_ate IS NOT NULL ORDER BY versao DESC""", (habito,))
    seguidas = 0
    for r in linhas:
        if r["desfecho"] == "falha":
            seguidas += 1
        else:
            break
    return seguidas


# ── 2. diff e envelope ───────────────────────────────────────────────────────
def achatar(obj, prefixo=""):
    """{'a': {'b': 1}, 'l': [{'c': 2}]} -> {'a.b': 1, 'l[0].c': 2}"""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(achatar(v, f"{prefixo}.{k}" if prefixo else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(achatar(v, f"{prefixo}[{i}]"))
    else:
        out[prefixo] = obj
    return out


def caminhos_alterados(atual, novo):
    a, b = achatar(atual), achatar(novo)
    return sorted(set(k for k in set(a) | set(b) if a.get(k) != b.get(k)))


def casa_regra(caminho, regra):
    import re
    padrao = "^" + re.escape(regra).replace(r"\[\]", r"\[\d+\]").replace(r"\*", r"[^.]+")
    padrao += r"($|[.\[])"
    return bool(re.match(padrao, caminho))


def classificar_mudancas(caminhos):
    """-> ('auto'|'pede_ok'|'proibido', motivo). Basta UM caminho fora do
    permitido para a proposta inteira precisar de gente."""
    ignorar = ("versao", "criada", "derivada_de", "autor", "desfecho_anterior")
    caminhos = [c for c in caminhos if not any(casa_regra(c, i) for i in ignorar)]
    if not caminhos:
        return "auto", "nada mudou além de metadados"
    for c in caminhos:
        if any(casa_regra(c, r) for r in ENVELOPE["aplica_sozinho"]):
            continue
        if any(casa_regra(c, r) for r in ENVELOPE["pede_ok"]):
            return "pede_ok", f"mexe em '{c}', que precisa de confirmação"
        return "pede_ok", f"'{c}' não está no envelope — só com gente no meio"
    return "auto", ", ".join(caminhos)


def checar_limites(spec_atual, spec_novo, medida):
    """Limites numéricos que não dependem de julgamento."""
    erros = []
    m0 = float(spec_atual["criterio_sucesso"]["adesao"]["min"])
    m1 = float(spec_novo["criterio_sucesso"]["adesao"]["min"])
    if abs(m1 - m0) > LIM["delta_meta_max"]:
        erros.append(f"meta saltaria de {m0:g} para {m1:g} (máx ±{LIM['delta_meta_max']})")
    if not (LIM["meta_min"] <= m1 <= LIM["meta_max"]):
        erros.append(f"meta fora de [{LIM['meta_min']}, {LIM['meta_max']}]: {m1:g}")
    if m1 > m0 and medida["adesao"] < 0.8:
        erros.append("subir a meta com adesão abaixo do critério é proibido pelo envelope")
    if len(spec_novo.get("gatilhos", [])) > LIM["max_gatilhos"]:
        erros.append(f"mais de {LIM['max_gatilhos']} gatilhos")
    h0, h1 = LIM["janela_gatilho_horas"]
    for g in spec_novo.get("gatilhos", []):
        if g.get("tipo") == "horario" and not (h0 <= int(g["quando"].split(":")[0]) <= h1):
            erros.append(f"gatilho fora da janela {h0}h-{h1}h: {g['quando']}")
    if int(spec_novo["horizonte"].get("dwell_min_semanas", 0)) < LIM["dwell_min_semanas"]:
        erros.append("dwell menor que o mínimo do envelope")
    return erros


# ── 3. o LLM (só diagnóstico e proposta) ─────────────────────────────────────
def propor(spec, medida, historico, falhadas):
    contexto = {
        "estrategia_atual": spec, "medicao": medida,
        "decisoes_anteriores": historico,
        "estrategias_falhadas_seguidas": falhadas,
        "pode_mexer_sozinho": ENVELOPE["aplica_sozinho"],
        "precisa_de_ok": ENVELOPE["pede_ok"],
        "proibido": ENVELOPE["proibido"], "limites": LIM,
    }
    prompt = f"""Você é o coach de hábitos. Analise os DADOS e proponha O PRÓXIMO PASSO.

DADOS (números já apurados — não recalcule, não invente):
{json.dumps(contexto, ensure_ascii=False, indent=2, default=str)}

Como pensar:
- quadrante 'ok': funcionou. Só suba de nível se houver folga real; senão mantenha e diga por quê.
- 'dose_insuficiente': a pessoa está cumprindo mas o objetivo não se move — o problema é a
  RECEITA, não a disciplina. Mexer na meta seria punir quem está fazendo a parte dela.
- 'nao_cabe': a estratégia não cabe na vida dela. Olhe os obstáculos e o que já foi tentado.
- 'resultado_declarado' false: a estratégia não tem critério de resultado. Declarar um
  (decisao 'declarar_resultado') costuma valer mais que qualquer outro ajuste.
- 'secundarios' são métricas ACOMPANHADAS que NÃO entram no quadrante: o hábito contribui
  para elas sem ser a alavanca principal. Use como contexto e mencione se andarem, mas NUNCA
  mude a estratégia porque um secundário não se moveu — seria cobrar do hábito errado.
- 'ritmo_semanal' é a velocidade observada da métrica de resultado (negativo = caindo).
  Compare com a taxa_semanal esperada no critério: ritmo bom com adesão baixa significa
  que outra coisa está fazendo o trabalho, e vale entender o quê antes de comemorar.
- silêncios altos = dado faltando, não preguiça: pode ser hora de mudar a coleta ou perguntar.
- NUNCA repita uma decisão que já falhou no histórico sem evidência nova.
- No máximo {LIM['mudancas_por_revisao']} mudanças, e uma hipótese só.

Responda SÓ um JSON:
{{"diagnostico": "<2-3 frases, concreto, citando os números>",
  "decisao": "<um de: {', '.join(DECISOES)}>",
  "mudancas": {{"<caminho.na.spec>": <valor novo>}},
  "hipotese": "<o que você espera que aconteça, testável>",
  "mensagem": "<1-2 frases para a pessoa, tom {spec['mensagens'].get('tom', 'parceiro')},
                máx 1 emoji, HTML do Telegram, ZERO cobrança ou culpa>"}}

Caminhos possíveis em "mudancas" (exemplos): "criterio_sucesso.adesao.min",
"criterio_sucesso.resultado", "gatilhos[0].quando", "gatilhos[0].dias",
"mensagens.lembrete", "horizonte.dwell_min_semanas". Use {{}} para não mudar nada.

FORMA de criterio_sucesso.resultado (proposta fora disto é recusada na validação):
{{"metrica": "<uma das declaradas em medicoes/coleta/derivadas da spec — não invente>",
  "direcao": "subir"|"descer"|"manter",     // opcional; use para métrica que precisa andar
  "taxa_semanal": <número POSITIVO>,         // opcional, só com direcao: ritmo esperado por semana
  "min": <número> | "max": <número>,         // alternativa a direcao: limiar por semana
  "alvo": <número>}}                          // opcional, informativo: a linha de chegada
Pelo menos um entre min, max e direcao é obrigatório."""
    return llm.perguntar_json(
        prompt, ("diagnostico", "decisao", "mudancas", "mensagem"),
        modelo="opus", timeout=300, origem="coach")


def aplicar_mudancas(spec, mudancas):
    """Aplica um patch caminho->valor sobre uma cópia da spec."""
    novo = json.loads(json.dumps(spec))
    for caminho, valor in mudancas.items():
        alvo, chaves = novo, []
        for parte in caminho.replace("]", "").replace("[", ".").split("."):
            if parte != "":
                chaves.append(int(parte) if parte.isdigit() else parte)
        for k in chaves[:-1]:
            alvo = alvo[k] if not isinstance(k, int) else alvo[k]
        alvo[chaves[-1]] = valor
    return novo


# ── comandos ─────────────────────────────────────────────────────────────────
def mensagem_padrao(spec, medida, prop):
    """Rede para quando a LLM devolve JSON válido mas sem texto. Revisão que
    acontece e não fala com ninguém é exatamente o buraco em que o coach velho
    ficou sete semanas."""
    nome = spec.get("nome") or spec["habito"]
    diag = (prop.get("diagnostico") or "").strip()
    if prop.get("decisao") == "conversa_humana":
        return (f"📋 Revisão de <b>{nome}</b>: {diag}\n\n"
                "Antes de mexer em qualquer parâmetro: o que está atrapalhando de verdade?")
    n = len(medida["semanas"])
    bateu = sum(1 for x in medida["semanas"] if x["bateu"])
    return f"📋 Revisão de <b>{nome}</b> ({bateu}/{n} semanas no alvo): {diag}"


def registrar_avaliacao(con, spec, medida, prop, aplicada, motivo):
    con.execute("""INSERT INTO avaliacoes (ts, habito, versao, adesao, resultado,
                   quadrante, decisao, aplicada, motivo, payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (R.agora(), spec["habito"], spec["versao"], medida["adesao"],
                 medida["resultado"], medida["quadrante"], prop.get("decisao"),
                 1 if aplicada else 0, motivo,
                 json.dumps({"medicao": medida, "proposta": prop},
                            ensure_ascii=False, default=str)))
    con.commit()


def cmd_avaliar(a, con):
    spec = E.carregar(a.habito)
    if spec["estado"] != "ativo":
        return {"pulado": f"hábito {spec['estado']}"}
    medida = medir(con, spec, a.em)

    # dwell: estratégia nova não pode ser julgada antes de ter tido chance
    dwell = int(spec["horizonte"].get("dwell_min_semanas", 2))
    if medida["semanas_avaliadas"] < dwell and not a.forcar:
        return {"pulado": f"só {medida['semanas_avaliadas']} semana(s) completas "
                          f"(dwell mínimo {dwell})", "medicao": medida}

    falhadas = estrategias_falhadas(con, a.habito)
    if falhadas >= LIM["estrategias_falhadas_teto"]:
        msg = (f"Já testamos {falhadas} estratégias para <b>{spec.get('nome')}</b> e "
               "nenhuma pegou. Em vez de ajustar mais um parâmetro: o que está "
               "realmente atrapalhando — e esse hábito ainda faz sentido agora?")
        msg = E.assinar(spec, msg)
        prop = {"decisao": "conversa_humana", "diagnostico": "teto de escalada atingido",
                "mudancas": {}, "mensagem": msg}
        if not a.dry_run:
            R.grava_evento(con, a.habito, "proposta", "coach", R.hoje(),
                           {"teto_escalada": falhadas})
            registrar_avaliacao(con, spec, medida, prop, False, "teto de escalada")
            subprocess.run([TG, msg], capture_output=True, timeout=30)
        return {"decisao": "conversa_humana", "medicao": medida, "mensagem": msg}

    prop, err = propor(spec, medida, historico_decisoes(con, a.habito), falhadas)
    if err:
        return {"erro": f"coach indisponível: {err}", "medicao": medida}

    mudancas = prop.get("mudancas") or {}
    resultado = {"medicao": medida, "diagnostico": prop.get("diagnostico"),
                 "decisao": prop.get("decisao"), "mudancas": mudancas}
    def recusar(motivo):
        """Proposta recusada ainda assim conversa: a revisão aconteceu, e o
        diagnóstico vale mesmo sem a mudança. Silêncio aqui esconderia tanto um
        coach confuso quanto uma semana que precisava de resposta."""
        resultado["recusado"] = motivo
        if not a.dry_run:
            registrar_avaliacao(con, spec, medida, prop, False, motivo)
            msg = (prop.get("mensagem") or "").strip() or mensagem_padrao(spec, medida, prop)
            subprocess.run([TG, E.assinar(spec, msg)], capture_output=True, timeout=30)
            resultado["mensagem"] = msg
        print(f"proposta recusada: {motivo}", file=sys.stderr)
        return resultado

    if len(mudancas) > LIM["mudancas_por_revisao"]:
        return recusar(f"{len(mudancas)} mudanças (máx {LIM['mudancas_por_revisao']})")

    novo = aplicar_mudancas(spec, mudancas) if mudancas else None
    veredito, motivo = "auto", "sem mudanças"
    if novo:
        novo["versao"] = spec["versao"] + 1
        novo["derivada_de"] = spec["versao"]
        novo["autor"] = "coach"
        novo["criada"] = R.hoje()
        novo["hipotese"] = prop.get("hipotese")
        novo["horizonte"]["revisar_em"] = E.proxima_revisao(novo, a.em)
        erros = checar_limites(spec, novo, medida)
        try:
            E.validar(novo)
        except E.Invalida as e:
            erros.append(str(e))
        if erros:
            return recusar("; ".join(erros))
        veredito, motivo = classificar_mudancas(caminhos_alterados(spec, novo))
    resultado["veredito"] = veredito
    resultado["motivo"] = motivo

    if a.dry_run:
        return resultado
    if novo and veredito == "auto":
        spec_fechada = dict(novo)
        spec_fechada["desfecho_anterior"] = ("sucesso" if medida["quadrante"] == "ok"
                                             else "falha")
        E.salvar_nova_versao(con, spec_fechada, "coach", prop.get("diagnostico", ""))
        resultado["nova_versao"] = spec_fechada["versao"]
    elif novo:
        R.grava_evento(con, a.habito, "proposta", "coach", R.hoje(),
                       {"mudancas": mudancas, "motivo": motivo,
                        "diagnostico": prop.get("diagnostico"),
                        "hipotese": prop.get("hipotese"), "spec": novo})
    else:
        # manteve a estratégia: só empurra a próxima revisão, sem inflar a
        # linhagem com uma "versão nova" que não mudou nada
        spec["horizonte"]["revisar_em"] = E.proxima_revisao(spec, a.em)
        open(E.caminho(a.habito), "w").write(
            json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
        resultado["revisar_em"] = spec["horizonte"]["revisar_em"]
    registrar_avaliacao(con, spec, medida, prop, veredito == "auto" and bool(novo), motivo)

    msg = (prop.get("mensagem") or "").strip() or mensagem_padrao(spec, medida, prop)
    if veredito == "pede_ok" and novo:
        # proposta fora do envelope espera gente: 👍 aplica, 👎 recusa e fica
        # registrado que a recusa foi decisão humana, não esquecimento
        import rotina
        msg += (f"\n\n🔧 Precisa do seu ok ({motivo}):\n<code>"
                + json.dumps(mudancas, ensure_ascii=False) +
                "</code>\n👍 aplico · 👎 deixo como está")
        rotina.perguntar(spec, msg, {"tipo": "aplicar_proposta"},
                         {"tipo": "nota", "texto": f"proposta recusada: {mudancas}"})
    elif msg:
        subprocess.run([TG, E.assinar(spec, msg)], capture_output=True, timeout=30)
    resultado["mensagem"] = msg
    return resultado


def cmd_aplicar(a, con):
    """Aplica a última proposta pendente (o 'ok' do humano)."""
    r = con.execute("""SELECT id, payload FROM eventos WHERE habito=? AND tipo='proposta'
                       ORDER BY id DESC LIMIT 1""", (a.habito,)).fetchone()
    if not r:
        return {"erro": "não há proposta pendente"}
    p = json.loads(r["payload"])
    if not p.get("spec"):
        return {"erro": "a última proposta não é aplicável (era conversa humana)"}
    versao = E.salvar_nova_versao(con, p["spec"], "rodrigo",
                                  "proposta do coach aprovada por " + a.por)
    R.grava_evento(con, a.habito, "decisao_humana", a.por, R.hoje(),
                   {"aprovou_proposta": r["id"], "versao": versao})
    con.commit()
    return {"aplicada": versao, "mudancas": p.get("mudancas")}


def cmd_simular(a, con):
    """Replay sobre o histórico real: com ciclo de revisão de semanas, sem isto
    você depura no ritmo do calendário. Por padrão só a parte determinística
    (não gasta request de LLM)."""
    spec = E.carregar(a.habito)
    de = a.de or con.execute("SELECT MIN(data) d FROM eventos WHERE habito=?",
                             (a.habito,)).fetchone()["d"]
    saida = []
    for semana in segundas(de, R.hoje()):
        m = medir(con, spec, semana, desde=de)
        if m["semanas_avaliadas"] < 1:
            continue
        linha = {"em": semana, "adesao": m["adesao"], "quadrante": m["quadrante"],
                 "semanas": m["semanas_avaliadas"],
                 "sessoes": [s["sessoes"] for s in m["semanas"]]}
        if a.com_llm:
            prop, err = propor(spec, m, historico_decisoes(con, a.habito), 0)
            linha["decisao"] = err or prop.get("decisao")
        saida.append(linha)
    return saida


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("avaliar"); sp.add_argument("habito"); sp.add_argument("--em")
    sp.add_argument("--dry-run", action="store_true"); sp.add_argument("--forcar", action="store_true")
    sp = sub.add_parser("aplicar"); sp.add_argument("habito"); sp.add_argument("--por", default="rodrigo")
    sp = sub.add_parser("simular"); sp.add_argument("habito"); sp.add_argument("--de")
    sp.add_argument("--com-llm", action="store_true")
    a = p.parse_args()
    con = R.conectar()
    print(json.dumps({"avaliar": cmd_avaliar, "aplicar": cmd_aplicar,
                      "simular": cmd_simular}[a.cmd](a, con),
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
