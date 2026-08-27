#!/usr/bin/env python3
"""migrar.py — traz o sistema velho (habits/<Pessoa>/*.json) para o registro novo.

Uma vez só. O que entra:
  log[] done=true  -> evento 'sessao' + métricas (value/unit, e a FC média que
                      estava presa no texto da nota)
  log[] done=false -> evento 'falha' (obstáculo 'nao_informado': o sistema velho
                      nunca perguntou o motivo)
  perfil.medicoes  -> métricas de RESULTADO (vo2max, peso, imc)
  adaptations[]    -> eventos 'avaliacao' + linhas em `avaliacoes`: é a memória
                      do coach velho (o que já foi tentado e falhou), que o coach
                      novo precisa para não repetir alavanca queimada
  metadados        -> estratégia v1 em habitos/estrategias/<habito>.json

Uso: migrar.py [--origem DIR] [--forcar]
"""
import argparse, glob, hashlib, json, os, re, sys, unicodedata
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)
sys.path.insert(0, DIR)
import registro as R

# Cada coach assina o que manda: com vários hábitos no mesmo chat, a assinatura
# é o que diz de quem é a mensagem antes de ela ser lida.
EMOJI_HABITO = {"exercicio": ("💪", "Exercícios")}
# hábitos descartados pelo Rodrigo: não voltam se a migração rodar de novo
IGNORAR = {"pausas_anti_sedentarismo"}
UNIDADE_CAMPO = {"min": ("minutos", "resultado"), "km": ("distancia", "resultado"),
                 "paginas": ("paginas", "resultado")}
MEDICOES_CAMPO = {"vo2max": ("vo2max", "ml/kg/min"), "peso_kg": ("peso", "kg"),
                  "imc": ("imc", None), "vo2_absoluto_lmin": ("vo2_absoluto", "l/min")}


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s.split("_")[0] if s.startswith("exercicio") else s


def fc_da_nota(nota):
    """As notas trazem 'FC média 122bpm' / '101bpm médio' — dado bom preso em prosa."""
    m = re.search(r"(\d{2,3})\s*bpm", nota or "", re.I)
    return float(m.group(1)) if m else None


def migrar_habito(con, fp, pessoa, forcar):
    h = json.load(open(fp))
    nome = h.get("name") or "sem_nome"
    hid = slug(nome)
    ja = con.execute("SELECT COUNT(*) FROM eventos WHERE habito=?", (hid,)).fetchone()[0]
    if ja and not forcar:
        print(f"  {hid}: já tem {ja} eventos — pulando (use --forcar)")
        return hid, 0
    n = 0
    for e in h.get("log", []):
        data = e.get("date")
        if not data:
            continue
        nota = e.get("note") or ""
        if e.get("done"):
            eid = R.grava_evento(con, hid, "sessao", "migracao", data,
                                 {"nota": nota, "origem_legado": os.path.basename(fp)})
            val, un = e.get("value"), (e.get("unit") or "").strip()
            if val is not None and un:
                campo, classe = UNIDADE_CAMPO.get(un, (un, "contexto"))
                R.grava_metrica(con, hid, campo, val, un, classe, "migracao", data, eid,
                                agregacao="soma")
            fc = fc_da_nota(nota)
            if fc:
                R.grava_metrica(con, hid, "fc_media", fc, "bpm", "contexto", "migracao",
                                data, eid, agregacao="media")
        else:
            R.grava_evento(con, hid, "falha", "migracao", data,
                           {"obstaculo": "nao_informado", "nota": nota})
        n += 1

    for a in h.get("adaptations", []):
        data = a.get("date")
        # adaptations[] do sistema velho misturava duas coisas: DECISÃO do coach
        # (tem change_type/by) e ANOTAÇÃO manual em texto livre (calibração da
        # Zona 2, perfil físico). Só a primeira é placar; a segunda é referência
        # — e é onde está o raciocínio que justifica a Zona 2 de 120-135 bpm.
        if not a.get("change_type"):
            R.grava_evento(con, hid, "nota", "migracao", data,
                           {"texto": a.get("change") or a.get("assessment") or "",
                            "origem_legado": "adaptations"})
            n += 1
            continue
        eid = R.grava_evento(con, hid, "avaliacao", "migracao", data, a)
        adesao = None
        m = re.match(r"^(\d+)\s*/\s*(\d+)$", str(a.get("result") or ""))
        if m and int(m.group(2)):
            adesao = int(m.group(1)) / int(m.group(2))
        con.execute("""INSERT INTO avaliacoes (ts, habito, versao, adesao, resultado,
                       quadrante, decisao, aplicada, motivo, payload)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"{data} 12:00:00", hid, 1, adesao, None, None,
                     a.get("change_type"), 1, a.get("assessment"),
                     json.dumps(a, ensure_ascii=False)))
        n += 1
    return hid, n


def estrategia_v1(con, fp, hid):
    """Destila a config ad-hoc numa spec v1. NÃO é uma hipótese — é o retrato do
    que estava no ar. A primeira estratégia de verdade (com critério declarado
    antes e horizonte) nasce com o coach, na fatia 4."""
    h = json.load(open(fp))
    spec = {
        "habito": hid, "versao": 1, "criada": R.hoje(), "derivada_de": None,
        # hábito sem NENHUM registro nunca esteve de pé de verdade (o
        # orquestrador velho nem lia type=daily): nasce suspenso, para não
        # poluir o status nem o coach com um hábito fantasma.
        "autor": "migracao",
        "estado": ("ativo" if h.get("status") == "active" and h.get("log")
                   else "suspenso"),
        "nome": h.get("name"), "motivacao": h.get("why", ""),
        "emoji": EMOJI_HABITO.get(hid, ("🎯", nome))[0],
        "coach": EMOJI_HABITO.get(hid, ("🎯", nome))[1],
        "hipotese": None,
        "observacao": "Reconstruída do sistema velho (ad-hoc). Sem hipótese nem "
                      "critério declarado antes — v2 nasce da primeira revisão do coach.",
        "criterio_sucesso": {
            "adesao": {"metrica": "sessoes_semana", "min": h.get("target_per_week", 1)},
            "resultado": None,
        },
        "horizonte": {"revisar_em": None, "dwell_min_semanas": 2},
        "gatilhos": ([{"tipo": "horario", "quando": h["cue_time"],
                       "dias": h.get("cue_days") or [1, 2, 3, 4, 5, 6, 7],
                       "msg": "lembrete"}] if h.get("cue_time") else []),
        "coleta": [
            {"campo": "minutos", "tipo": "numero", "unidade": "min", "obrigatorio": True},
            {"campo": "fc_media", "tipo": "numero", "unidade": "bpm"},
            {"campo": "obstaculo", "tipo": "enum", "quando": "falha",
             "valores": ["agenda", "cansaco", "esqueci", "ambiente", "doenca",
                         "viagem", "sem_vontade"]},
        ],
        "mensagens": {
            "modo": "template",   # template | llm (llm cai no template se falhar)
            "tom": "parceiro, experimento, zero cobrança",
            "versao_minima": h.get("tiny", ""),
            "lembrete": "⏰ <b>{nome}</b>  {barra}  ({sessoes}/{meta} esta semana)"
                        "\n💡 <i>{versao_minima}</i>",
        },
        "gates": {"max_msgs_dia": 1, "janela_horas": [9, 22]},
        "recursos": [],
    }
    destino = os.path.join(DIR, "estrategias", f"{hid}.json")
    os.makedirs(os.path.join(DIR, "estrategias", hid), exist_ok=True)
    txt = json.dumps(spec, ensure_ascii=False, indent=2)
    open(destino, "w").write(txt + "\n")
    open(os.path.join(DIR, "estrategias", hid, "v1.json"), "w").write(txt + "\n")
    # ativa_de = quando o hábito nasceu, não quando migramos: a v1 é o retrato de
    # uma estratégia que JÁ estava no ar, e datá-la de hoje jogaria fora o
    # histórico inteiro na primeira avaliação do coach.
    nascimento = (datetime.fromtimestamp(h["created"]).strftime("%Y-%m-%d")
                  if h.get("created") else R.hoje())
    con.execute("""INSERT OR REPLACE INTO estrategias
                   (habito, versao, ativa_de, ativa_ate, arquivo, hash, autor, hipotese)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (hid, 1, nascimento, None, os.path.relpath(destino, RAIZ),
                 hashlib.sha256(txt.encode()).hexdigest()[:16], "migracao", None))
    R.grava_evento(con, hid, "estrategia_ativada", "migracao", nascimento,
                   {"versao": 1, "origem": "migração do sistema velho"})
    return destino


def migrar_perfil(con, fp, hid):
    p = json.load(open(fp))
    n = 0
    for med in p.get("medicoes", []):
        data = med.get("data")
        if not data:
            continue
        for k, (campo, un) in MEDICOES_CAMPO.items():
            if med.get(k) is None:
                continue
            # idempotente: rodar a migração de novo não pode duplicar medição
            ja = con.execute("""SELECT COUNT(*) FROM metricas
                                 WHERE habito=? AND campo=? AND data=? AND fonte='perfil'""",
                             (hid, campo, data)).fetchone()[0]
            if ja:
                continue
            # medição corporal é ponto no tempo: nunca se soma
            R.grava_metrica(con, hid, campo, med[k], un, "resultado", "perfil", data,
                            agregacao="ultimo")
            n += 1
    metas = p.get("metas", {})
    ja_ref = con.execute("SELECT COUNT(*) FROM eventos WHERE habito=? AND tipo='referencia'",
                         (hid,)).fetchone()[0]
    if metas and not ja_ref:
        R.grava_evento(con, hid, "referencia", "migracao", R.hoje(),
                       {"perfil": {k: p.get(k) for k in ("nascimento", "altura_cm")},
                        "metas": metas})
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origem", default=os.path.join(RAIZ, "habits"))
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args()
    con = R.conectar()
    total = 0
    for pdir in sorted(glob.glob(os.path.join(a.origem, "*"))):
        if not os.path.isdir(pdir):
            continue
        pessoa = os.path.basename(pdir)
        print(f"pessoa: {pessoa}")
        principal = None
        for fp in sorted(glob.glob(os.path.join(pdir, "*.json"))):
            if os.path.basename(fp) == "perfil.json":
                continue
            if slug(json.load(open(fp)).get("name", "")) in IGNORAR:
                print(f"  {os.path.basename(fp)}: ignorado (hábito descartado)")
                continue
            hid, n = migrar_habito(con, fp, pessoa, a.forcar)
            # a spec v1 é escrita uma vez por hábito (inclusive para hábito sem
            # log: os metadados — motivação, versão mínima, gatilho — se perderiam
            # junto com o habits/ velho)
            tem = con.execute("SELECT COUNT(*) FROM estrategias WHERE habito=?",
                              (hid,)).fetchone()[0]
            if not tem:
                estrategia_v1(con, fp, hid)
            print(f"  {hid}: {n} registros")
            total += n
            if principal is None:
                principal = hid
        perfil = os.path.join(pdir, "perfil.json")
        if os.path.exists(perfil) and principal:
            n = migrar_perfil(con, perfil, principal)
            print(f"  perfil -> {n} métricas de resultado em '{principal}'")
            total += n
    con.commit()
    print(f"total: {total} registros em {R.DB}")


if __name__ == "__main__":
    main()
