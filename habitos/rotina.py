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
def enviar(canal, texto, dry=False):
    if dry:
        print(f"[dry-run] {canal}: {texto}")
        return True
    if canal.startswith("telegram_kid:"):
        cmd = [NOTIFY_KIDS, texto, canal.split(":", 1)[1]]
    else:
        cmd = [TG_NOTIFY, texto]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except Exception as e:                                   # noqa: BLE001
        print(f"falha ao enviar: {e}", file=sys.stderr)
        return False


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
def processar_gatilhos(con, spec, agora, dry):
    habito, dia = spec["habito"], agora.date().isoformat()
    enviados = 0
    if pausado(con, habito, dia):
        return 0
    gates = spec["gates"]
    if lembretes_do_dia(con, habito, dia) >= int(gates.get("max_msgs_dia", 1)):
        return 0
    if ja_registrou(con, habito, dia):
        return 0                      # já fez (ou já disse que não fez) hoje
    for i, g in enumerate(spec["gatilhos"]):
        if g.get("tipo") != "horario":
            continue                  # gatilho por evento entra na fatia de sensores
        if agora.isoweekday() not in (g.get("dias") or []):
            continue
        hh, mm = (int(x) for x in g["quando"].split(":"))
        alvo = agora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if abs((agora - alvo).total_seconds()) > TOLERANCIA_MIN * 60:
            continue
        if lembretes_do_dia(con, habito, dia, i):
            continue
        ctx = contexto(con, spec, agora)
        texto = render(spec, g.get("msg", "lembrete"), ctx)
        if not texto.strip():
            continue
        if enviar(spec.get("canal", "telegram_admin"), texto, dry):
            enviados += 1
            if not dry:
                R.grava_evento(con, habito, "lembrete", "rotina", dia,
                               {"gatilho": i, "msg": g.get("msg"), "texto": texto,
                                "hora": agora.strftime("%H:%M")})
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
    sp = sub.add_parser("pausar"); sp.add_argument("habito")
    sp.add_argument("--ate"); sp.add_argument("--motivo", default="")
    sp = sub.add_parser("retomar"); sp.add_argument("habito")
    a = p.parse_args()
    con = R.conectar()
    print(json.dumps({"tick": cmd_tick, "pausar": cmd_pausar,
                      "retomar": cmd_retomar}[a.cmd](a, con),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
