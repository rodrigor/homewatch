#!/usr/bin/env python3
"""rotina.py — executa a estratégia corrente. NÃO decide nada.

É o atuador da malha: lê a spec, dispara gatilho quando é hora, respeita os
gates, registra o que fez e cala a boca quando o hábito está pausado. Toda
decisão (mudar meta, trocar gatilho, desistir) é do coach — aqui só se cumpre o
que a estratégia declarou.

Uso:
  rotina.py tick [--dry-run] [--agora "AAAA-MM-DD HH:MM"] [--habito X]
  rotina.py pausar <habito> [--ate AAAA-MM-DD] [--motivo "viagem"]
  rotina.py retomar <habito>
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)
sys.path.insert(0, DIR)
import registro as R
import estrategia as E
import llm

TOLERANCIA_MIN = 10          # janela em torno do horário do gatilho: menor que o
                             # intervalo do tick (15 min) para o mesmo gatilho não
                             # cair em dois ticks e disparar 15 min adiantado
TG_NOTIFY = os.path.join(RAIZ, "tg_notify.sh")
NOTIFY_KIDS = os.path.join(RAIZ, "notify_kids.sh")


# ── envio ────────────────────────────────────────────────────────────────────
def enviar(canal, texto, dry=False, quer_id=False):
    """-> True/False, ou o message_id quando quer_id (para a reação achar a
    pergunta depois)."""
    if dry:
        print(f"[dry-run] {canal}: {texto}")
        return "dry" if quer_id else True
    if canal.startswith("telegram_kid:"):
        cmd = [NOTIFY_KIDS, texto, canal.split(":", 1)[1]]
    else:
        cmd = [TG_NOTIFY] + (["--id"] if quer_id else []) + [texto]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:                                   # noqa: BLE001
        print(f"falha ao enviar: {e}", file=sys.stderr)
        return False
    if p.returncode != 0:
        return False
    return (p.stdout or "").strip() if quer_id else True


def perguntar(spec, texto, sim, nao, dry=False):
    """Manda uma pergunta de sim/não e deixa a resposta pronta para chegar por
    reação. A ação de cada lado é declarada AGORA, não interpretada depois."""
    msg_id = enviar(spec.get("canal", "telegram_admin"), E.assinar(spec, texto),
                    dry, quer_id=True)
    if not msg_id or dry:
        return msg_id
    subprocess.run([os.path.join(DIR, "perguntas.py"), "registrar", str(msg_id),
                    spec["habito"], "--texto", texto,
                    "--sim", json.dumps(sim), "--nao", json.dumps(nao)],
                   capture_output=True, timeout=30)
    return msg_id


# ── contexto para renderizar mensagem ────────────────────────────────────────
def contexto(con, spec, quando):
    habito = spec["habito"]
    semana = (quando.date() - timedelta(days=quando.weekday())).isoformat()
    sessoes = con.execute(
        "SELECT COALESCE(sessoes,0) FROM v_sessoes_semanais WHERE habito=? AND semana=?",
        (habito, semana)).fetchone()
    sessoes = sessoes[0] if sessoes else 0
    meta = int(spec["criterio_sucesso"]["adesao"]["min"])
    return {
        "nome": spec.get("nome") or habito, "habito": habito,
        "sessoes": sessoes, "meta": meta,
        "barra": "🟢" * min(sessoes, meta) + "⚪" * max(0, meta - sessoes),
        "versao_minima": spec["mensagens"].get("versao_minima", ""),
        "motivacao": spec.get("motivacao", ""), "semana": semana,
    }


def render(spec, chave, ctx, origem="rotina"):
    """Template por padrão. Modo 'llm' redige na hora — mas SEMPRE com o template
    como rede: mensagem que não sai é pior que mensagem genérica."""
    tpl = spec["mensagens"].get(chave, "")
    try:
        texto = tpl.format(**ctx)
    except KeyError as e:
        texto = tpl
        print(f"template {chave} usa campo inexistente {e}", file=sys.stderr)
    if spec["mensagens"].get("modo") != "llm":
        return texto
    prompt = (f"Você é um coach de hábitos, parceiro de {ctx['nome']}. "
              f"Tom: {spec['mensagens'].get('tom', 'leve e direto')}.\n"
              f"Situação: é a hora combinada do hábito \"{ctx['nome']}\". "
              f"Progresso da semana: {ctx['sessoes']} de {ctx['meta']}. "
              f"Versão mínima combinada: {ctx['versao_minima']}. "
              f"Motivação dele: {ctx['motivacao']}.\n"
              "Escreva UMA mensagem de 1-2 frases, no máximo 1 emoji, HTML do "
              "Telegram (<b>/<i>), ZERO cobrança ou culpa. Responda só a mensagem.")
    txt, err = llm.perguntar(prompt, origem=f"rotina/{chave}")
    if err:
        print(f"llm indisponível ({err}) — usando template", file=sys.stderr)
        return texto
    return txt


# ── estado do hábito ─────────────────────────────────────────────────────────
def pausado(con, habito, dia):
    """Pausa é de primeira classe (viagem, doença). No sistema velho isso virava
    sequência de faltas e envenenava o diagnóstico do coach."""
    r = con.execute("""SELECT tipo, payload, data FROM eventos
                       WHERE habito=? AND tipo IN ('pausa_inicio','pausa_fim')
                       ORDER BY data DESC, id DESC LIMIT 1""", (habito,)).fetchone()
    if not r or r["tipo"] != "pausa_inicio":
        return False
    ate = (json.loads(r["payload"]) or {}).get("ate")
    return True if not ate else dia <= ate


def ja_registrou(con, habito, dia):
    return con.execute("""SELECT COUNT(*) FROM eventos WHERE habito=? AND data=?
                          AND tipo IN ('sessao','falha')""", (habito, dia)).fetchone()[0] > 0


def lembretes_do_dia(con, habito, dia, gatilho=None):
    q = "SELECT COUNT(*) FROM eventos WHERE habito=? AND data=? AND tipo='lembrete'"
    args = [habito, dia]
    if gatilho is not None:
        q += " AND json_extract(payload,'$.gatilho') = ?"
        args.append(gatilho)
    return con.execute(q, args).fetchone()[0]


# ── o tick ───────────────────────────────────────────────────────────────────
def medido_recentemente(con, habito, campo, dia, cada_dias):
    ultima = con.execute("""SELECT MAX(data) d FROM metricas WHERE habito=? AND campo=?""",
                         (habito, campo)).fetchone()["d"]
    if not ultima:
        return False
    return (datetime.strptime(dia, "%Y-%m-%d")
            - datetime.strptime(ultima, "%Y-%m-%d")).days < int(cada_dias)


def horario_aprendido(con, habito, g):
    """Mediana do horário em que a pessoa REALMENTE registra, das últimas N vezes.

    Mediana e não média: um registro perdido às 23h desloca a média e não a
    mediana. Enquanto não houver amostras suficientes, vale quando_padrao — e o
    gatilho vai se mudando sozinho conforme a rotina da pessoa muda, sem
    ninguém precisar editar a estratégia.
    """
    n = int(g.get("amostras", 10))
    tipos = g.get("aprende_de", "sessao")
    linhas = con.execute(
        """SELECT ts FROM eventos WHERE habito=? AND tipo=? AND origem != 'rotina'
           ORDER BY id DESC LIMIT ?""", (habito, tipos, n)).fetchall()
    marcas = []          # minuto do dia de cada registro (0..1439)
    for r in linhas:
        try:
            t = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        marcas.append(t.hour * 60 + t.minute)
    if len(marcas) < int(g.get("minimo_amostras", 3)):
        return g.get("quando_padrao"), len(marcas)
    marcas.sort()
    meio = marcas[len(marcas) // 2]
    return f"{meio // 60:02d}:{meio % 60:02d}", len(marcas)


def processar_gatilhos(con, spec, agora, dry):
    habito, dia = spec["habito"], agora.date().isoformat()
    enviados = 0
    if pausado(con, habito, dia):
        return 0
    gates = spec["gates"]
    if lembretes_do_dia(con, habito, dia) >= int(gates.get("max_msgs_dia", 1)):
        return 0
    fez_hoje = ja_registrou(con, habito, dia)
    for i, g in enumerate(spec["gatilhos"]):
        if g.get("tipo") != "horario":
            continue                  # gatilho por evento entra na fatia de sensores
        alvo = g.get("para", "sessao")
        # sessão já registrada silencia o lembrete de sessão, mas não o de
        # medição: são coisas diferentes e a segunda alimenta o critério de
        # resultado.
        if alvo == "sessao" and fez_hoje:
            continue
        if alvo == "medicao" and medido_recentemente(con, habito, g["campo"], dia,
                                                     g.get("cada_dias", 7)):
            continue
        if agora.isoweekday() not in (g.get("dias") or []):
            continue
        quando = g["quando"]
        if quando == "auto":
            quando, amostras = horario_aprendido(con, habito, g)
            if not quando:
                continue
        hh, mm = (int(x) for x in quando.split(":"))
        alvo = agora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if abs((agora - alvo).total_seconds()) > TOLERANCIA_MIN * 60:
            continue
        if lembretes_do_dia(con, habito, dia, i):
            continue
        ctx = contexto(con, spec, agora)
        texto = render(spec, g.get("msg", "lembrete"), ctx)
        if not g.get("pergunta"):
            texto = E.assinar(spec, texto)   # perguntar() já assina
        if not texto.strip():
            continue
        perg = g.get("pergunta")
        entregue = (perguntar(spec, texto, perg["sim"], perg["nao"], dry) if perg
                    else enviar(spec.get("canal", "telegram_admin"), texto, dry))
        if entregue:
            enviados += 1
            if not dry:
                R.grava_evento(con, habito, "lembrete", "rotina", dia,
                               {"gatilho": i, "msg": g.get("msg"), "texto": texto,
                                "para": alvo, "hora": agora.strftime("%H:%M"),
                                "horario_usado": quando, "pergunta": bool(g.get("pergunta")),
                                "aprendido": g["quando"] == "auto"})
                con.commit()
    return enviados


def varrer_silencio(con, spec, agora, dry):
    """Lembrete que não teve resposta vira evento 'silencio' — nunca 'falha'.
    Silêncio é dado faltando, e o coach precisa saber a diferença entre 'não fez'
    e 'não sei'."""
    habito = spec["habito"]
    ontem = (agora.date() - timedelta(days=1)).isoformat()
    if not lembretes_do_dia(con, habito, ontem):
        return 0
    if ja_registrou(con, habito, ontem):
        return 0
    ja = con.execute("""SELECT COUNT(*) FROM eventos WHERE habito=? AND data=?
                        AND tipo='silencio'""", (habito, ontem)).fetchone()[0]
    if ja:
        return 0
    if dry:
        print(f"[dry-run] silêncio em {habito} @ {ontem}")
        return 1
    R.grava_evento(con, habito, "silencio", "rotina", ontem,
                   {"motivo": "lembrete sem resposta"})
    con.commit()
    return 1


def revisao_devida(spec, agora):
    rev = spec["horizonte"].get("revisar_em")
    return bool(rev) and agora.date().isoformat() >= rev


def cmd_tick(a, con):
    agora = datetime.strptime(a.agora, "%Y-%m-%d %H:%M") if a.agora else datetime.now()
    resumo = {"agora": agora.strftime("%Y-%m-%d %H:%M"), "lembretes": 0,
              "silencios": 0, "revisoes": []}
    for habito in E.listar():
        if a.habito and habito != a.habito:
            continue
        spec = E.carregar(habito)
        try:
            E.validar(spec)
        except E.Invalida as e:
            print(f"{habito}: estratégia inválida, ignorando ({e})", file=sys.stderr)
            continue
        if spec["estado"] != "ativo":
            continue
        resumo["silencios"] += varrer_silencio(con, spec, agora, a.dry_run)
        resumo["lembretes"] += processar_gatilhos(con, spec, agora, a.dry_run)
        if revisao_devida(spec, agora):
            resumo["revisoes"].append(habito)
    # o coach é chamado pela rotina, mas decide sozinho (e só se existir)
    coach = os.path.join(DIR, "coach.py")
    for habito in resumo["revisoes"]:
        if os.path.exists(coach) and not a.dry_run:
            subprocess.run([coach, "avaliar", habito], timeout=600)
    return resumo


# ── parecer: a métrica estimula quem se interessa por ela ────────────────────
def valor_anterior(con, escopo, campo, antes_de_id):
    r = con.execute("""SELECT valor_num, data, unidade FROM metricas
                       WHERE escopo=? AND campo=? AND id < ? AND valor_num IS NOT NULL
                       ORDER BY id DESC LIMIT 1""", (escopo, campo, antes_de_id)).fetchone()
    return dict(r) if r else None


def contexto_parecer(con, spec, campos, escopo):
    """O que este coach precisa saber para opinar: o que mudou, quanto mudou, e
    o que isso significa PARA ELE (o mesmo peso é resultado de um coach e
    secundário de outro)."""
    import coach as C
    novidades = []
    for campo in campos:
        atual = con.execute("""SELECT id, valor_num, unidade, data FROM metricas
                               WHERE escopo=? AND campo=? AND valor_num IS NOT NULL
                               ORDER BY id DESC LIMIT 1""", (escopo, campo)).fetchone()
        if not atual:
            continue
        ant = valor_anterior(con, escopo, campo, atual["id"])
        novidades.append({
            "campo": campo, "papel": E.papel_do_campo(spec, campo),
            "valor": atual["valor_num"], "unidade": atual["unidade"],
            "anterior": ant["valor_num"] if ant else None,
            "desde": ant["data"] if ant else None,
            "variacao": (round(atual["valor_num"] - ant["valor_num"], 3) if ant else None),
        })
    return {"novidades": novidades, "medicao": C.medir(con, spec),
            "objetivo": spec.get("objetivo"),
            "criterio": spec.get("criterio_sucesso")}


def pareceres_do_dia(con, habito, dia):
    return con.execute("""SELECT COUNT(*) FROM eventos WHERE habito=? AND data=?
                          AND tipo='parecer'""", (habito, dia)).fetchone()[0]


def emitir_parecer(con, spec, campos, escopo, dry=False):
    habito, dia = spec["habito"], R.hoje()
    limite = int((spec.get("parecer") or {}).get("max_por_dia", 2))
    if pareceres_do_dia(con, habito, dia) >= limite:
        return None
    ctx = contexto_parecer(con, spec, campos, escopo)
    if not ctx["novidades"]:
        return None
    prompt = f"""Você é o coach do hábito "{spec.get('nome') or habito}". Acabou de chegar
dado novo que te interessa. Dê um PARECER curto — não é revisão de estratégia.

DADOS (já apurados; não recalcule):
{json.dumps(ctx, ensure_ascii=False, indent=2, default=str)}

Regras:
- 1 a 3 frases. Tom: {spec['mensagens'].get('tom', 'parceiro, direto')}. Máx 1 emoji.
- Cite os NÚMEROS que chegaram e o que eles significam PARA ESTE HÁBITO (veja 'papel':
  'resultado' é o que te julga; 'secundario' você acompanha mas não controla; 'medicao'
  e 'coleta' são insumo).
- Se o papel for 'secundario', deixe claro que é acompanhamento — não puxe para si o
  mérito nem a culpa do que outro hábito controla.
- NÃO proponha mudança de meta, gatilho ou estratégia: isso é da revisão, que tem data.
  Se algo parecer urgente, diga em uma frase que vale antecipar a revisão.
- Sem sermão, sem culpa, sem plano de ação genérico. HTML do Telegram (<b>/<i>).
Responda só a mensagem."""
    txt, err = llm.perguntar(prompt, origem=f"parecer/{habito}", timeout=120)
    if err:
        print(f"parecer de {habito} indisponível: {err}", file=sys.stderr)
        return None
    msg = E.assinar(spec, txt)
    if dry:
        print(f"[dry-run] parecer {habito}: {msg}")
        return msg
    if enviar(spec.get("canal", "telegram_admin"), msg):
        R.grava_evento(con, habito, "parecer", "coach", dia,
                       {"campos": campos, "escopo": escopo, "texto": msg})
        con.commit()
    return msg


def cmd_reagir(a, con):
    """Estimula os coaches interessados nos campos que acabaram de mudar."""
    campos = [c for c in a.campos.split(",") if c]
    saida = {"campos": campos, "pareceres": []}
    # um parecer por coach, cobrindo todos os campos que interessam a ele — não
    # um parecer por campo (um relatório de balança com 11 números viraria 11
    # mensagens)
    porhabito = {}
    for campo in campos:
        for hid, spec, papel in E.interessados(campo, a.escopo):
            porhabito.setdefault(hid, (spec, []))[1].append(campo)
    for hid, (spec, cs) in porhabito.items():
        if pausado(con, hid, R.hoje()):
            continue
        msg = emitir_parecer(con, spec, cs, a.escopo, a.dry_run)
        saida["pareceres"].append({"habito": hid, "campos": cs,
                                   "emitido": bool(msg), "texto": msg})
    return saida


def cmd_pausar(a, con):
    R.grava_evento(con, a.habito, "pausa_inicio", "manual", R.hoje(),
                   {"ate": a.ate, "motivo": a.motivo})
    con.commit()
    return {"pausado": a.habito, "ate": a.ate or "sem data", "motivo": a.motivo}


def cmd_retomar(a, con):
    R.grava_evento(con, a.habito, "pausa_fim", "manual", R.hoje(), {})
    con.commit()
    return {"retomado": a.habito}


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("tick"); sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--agora"); sp.add_argument("--habito")
    sp = sub.add_parser("reagir"); sp.add_argument("--campos", required=True)
    sp.add_argument("--escopo", required=True); sp.add_argument("--dry-run", action="store_true")
    sp = sub.add_parser("pausar"); sp.add_argument("habito")
    sp.add_argument("--ate"); sp.add_argument("--motivo", default="")
    sp = sub.add_parser("retomar"); sp.add_argument("habito")
    a = p.parse_args()
    con = R.conectar()
    print(json.dumps({"tick": cmd_tick, "reagir": cmd_reagir, "pausar": cmd_pausar,
                      "retomar": cmd_retomar}[a.cmd](a, con),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
