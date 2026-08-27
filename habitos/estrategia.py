#!/usr/bin/env python3
"""estrategia.py — carrega, valida e versiona a estratégia corrente.

A estratégia é DADO, não código: declara só primitivas que a rotina sabe
executar. Quando ela precisa de algo que não existe, isso não é o coach
escrevendo script — é um pedido de capacidade para um humano.

O arquivo em habitos/estrategias/<habito>.json é a fonte de verdade; a tabela
`estrategias` é a linha do tempo (que versão estava no ar quando), para dar join
com eventos e métricas na hora de julgar se a estratégia funcionou.

Uso:
  estrategia.py validar <habito>
  estrategia.py mostrar <habito>
  estrategia.py ativas
"""
import hashlib, json, os, sys
from datetime import date, datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(DIR)
EST = os.path.join(DIR, "estrategias")
sys.path.insert(0, DIR)
import registro as R

TIPOS_GATILHO = {"horario", "evento"}
DIRECOES = {"subir", "descer", "manter"}
# Um gatilho pode cobrar a sessão ou a MEDIÇÃO. Sem essa distinção, o critério
# de resultado depende de um dado que ninguém lembra de registrar — e a malha
# fica aberta exatamente no ponto que interessa.
ALVOS_GATILHO = {"sessao", "medicao"}
# Linguagem fechada das métricas derivadas. Fechada de propósito: é o que
# permite ao conhecimento de domínio ("este campo só conta quando aquele outro
# fica nesta faixa") morar no ARQUIVO da estratégia, como número, em vez de
# virar código aqui dentro.
OPERADORES = {"entre", "min", "max", "igual"}
ESTADOS = {"ativo", "pausado", "suspenso"}
AGREGACOES = {"soma", "media", "media_dia", "ultimo"}
# "pessoa" = métrica que não pertence a um hábito e sim a quem o pratica, e por
# isso pode ser lida por mais de um coach ao mesmo tempo. (Multi-pessoa, quando
# existir, vira "pessoa:<nome>".)
ESCOPOS = {"habito", "pessoa"}
# Primitivas que a rotina sabe executar. Estratégia que peça outra coisa é
# recusada na validação — é assim que o coach fica preso a mexer em parâmetros.
CAMPOS_OBRIGATORIOS = {"habito", "versao", "estado", "criterio_sucesso",
                       "horizonte", "gatilhos", "coleta", "mensagens", "gates"}


class Invalida(Exception):
    pass


EMOJI_PADRAO = "🎯"


def assinar(spec, texto):
    """Toda mensagem sai com o cabeçalho do coach que a mandou:

        {emoji} <b>Coach: {nome}</b>

        <mensagem>

    Com mais de um hábito no mesmo chat do Telegram, mensagem sem cabeçalho
    chega órfã: a pessoa não sabe quem está falando nem sobre o quê."""
    emoji = spec.get("emoji") or EMOJI_PADRAO
    nome = spec.get("coach") or spec.get("nome") or spec["habito"]
    texto = (texto or "").strip()
    cabecalho = f"{emoji} <b>Coach: {nome}</b>"
    return texto if texto.startswith(emoji) else f"{cabecalho}\n\n{texto}"


def escopo_de(spec, campo):
    """Em que escopo esta métrica é lida/gravada: o hábito ou a pessoa."""
    for bloco in ("medicoes", "coleta", "derivadas"):
        for item in spec.get(bloco, []) or []:
            if item.get("campo") == campo:
                return "pessoa" if item.get("escopo") == "pessoa" else spec["habito"]
    return spec["habito"]


def caminho(habito):
    return os.path.join(EST, f"{habito}.json")


def carregar(habito):
    fp = caminho(habito)
    if not os.path.exists(fp):
        raise Invalida(f"sem estratégia para '{habito}'")
    return json.load(open(fp))


def listar():
    if not os.path.isdir(EST):
        return []
    return sorted(os.path.splitext(os.path.basename(f))[0]
                  for f in os.listdir(EST) if f.endswith(".json"))


def validar(spec):
    """Recusa spec malformada ANTES de ela virar comportamento. O coach escreve
    aqui: sem validação, um campo torto vira lembrete às 3h da manhã."""
    faltam = CAMPOS_OBRIGATORIOS - set(spec)
    if faltam:
        raise Invalida(f"campos obrigatórios ausentes: {sorted(faltam)}")
    if spec["estado"] not in ESTADOS:
        raise Invalida(f"estado inválido: {spec['estado']} (use {sorted(ESTADOS)})")
    if not isinstance(spec["versao"], int) or spec["versao"] < 1:
        raise Invalida("versao deve ser inteiro >= 1")

    cs = spec["criterio_sucesso"]
    ad = cs.get("adesao")
    if not ad or "min" not in ad:
        raise Invalida("criterio_sucesso.adesao.min é obrigatório")
    if not isinstance(ad["min"], (int, float)) or ad["min"] <= 0:
        raise Invalida("criterio_sucesso.adesao.min deve ser > 0")
    res = cs.get("resultado")
    if res:
        if "metrica" not in res:
            raise Invalida("criterio_sucesso.resultado precisa de 'metrica'")
        if res.get("direcao") and res["direcao"] not in DIRECOES:
            raise Invalida(f"direcao inválida: {res['direcao']} (use {sorted(DIRECOES)})")
        if not any(k in res for k in ("min", "max", "direcao")):
            raise Invalida("criterio_sucesso.resultado precisa de min, max ou direcao — "
                           "sem isso não há como dizer se o resultado andou")
        if res.get("taxa_semanal") is not None and not res.get("direcao"):
            raise Invalida("taxa_semanal só faz sentido com direcao")
        conhecidas = {m["campo"] for m in spec.get("medicoes", [])}
        conhecidas |= {c["campo"] for c in spec.get("coleta", [])}
        conhecidas |= {d["campo"] for d in spec.get("derivadas", [])}
        if res["metrica"] not in conhecidas:
            raise Invalida(f"criterio_sucesso.resultado aponta para '{res['metrica']}', que "
                           f"não é coletada, medida nem derivada. Declarar uma métrica nova "
                           f"é pedido de capacidade, não decisão do coach.")

    for sec in cs.get("secundarios", []) or []:
        if "metrica" not in sec:
            raise Invalida("secundário precisa de 'metrica'")
        if sec.get("direcao") and sec["direcao"] not in DIRECOES:
            raise Invalida(f"direcao inválida no secundário {sec['metrica']}: {sec['direcao']}")
        conhecidas = ({m["campo"] for m in spec.get("medicoes", [])}
                      | {c["campo"] for c in spec.get("coleta", [])}
                      | {d["campo"] for d in spec.get("derivadas", [])})
        if sec["metrica"] not in conhecidas:
            raise Invalida(f"secundário aponta para '{sec['metrica']}', que não é "
                           f"coletada, medida nem derivada")

    for m in spec.get("medicoes", []) + spec.get("coleta", []) + spec.get("derivadas", []):
        if m.get("escopo", "habito") not in ESCOPOS:
            raise Invalida(f"escopo inválido em {m.get('campo')}: {m['escopo']} "
                           f"(use {sorted(ESCOPOS)})")
    for m in spec.get("medicoes", []):
        if "campo" not in m:
            raise Invalida(f"medição sem campo: {m}")
        if m.get("agregacao", "ultimo") not in AGREGACOES:
            raise Invalida(f"agregacao inválida em {m['campo']}: {m['agregacao']}")

    campos_sessao = {c["campo"] for c in spec.get("coleta", [])}
    for d in spec.get("derivadas", []):
        if "campo" not in d or "de" not in d:
            raise Invalida(f"derivada precisa de 'campo' e 'de': {d}")
        if d["de"] not in campos_sessao:
            raise Invalida(f"derivada {d['campo']} vem de '{d['de']}', que não está na coleta")
        for campo_cond, cond in (d.get("quando") or {}).items():
            if campo_cond not in campos_sessao:
                raise Invalida(f"derivada {d['campo']} testa '{campo_cond}', fora da coleta")
            desconhecidos = set(cond) - OPERADORES
            if desconhecidos:
                raise Invalida(f"operador desconhecido em {d['campo']}: {sorted(desconhecidos)} "
                               f"(a rotina só sabe {sorted(OPERADORES)})")

    hz = spec["horizonte"]
    if hz.get("revisar_em"):
        try:
            date.fromisoformat(hz["revisar_em"])
        except ValueError:
            raise Invalida(f"horizonte.revisar_em inválido: {hz['revisar_em']}")
    if int(hz.get("dwell_min_semanas", 0)) < 1:
        raise Invalida("horizonte.dwell_min_semanas deve ser >= 1: estratégia que "
                       "pode ser trocada a qualquer momento nunca é testada")

    emoji = spec.get("emoji", "")
    if emoji and len(emoji) > 4:
        raise Invalida(f"emoji deve ser 1-2 caracteres: {emoji!r}")

    declaradas = {m["campo"] for m in spec.get("medicoes", [])}
    for g in spec["gatilhos"]:
        if g.get("para", "sessao") not in ALVOS_GATILHO:
            raise Invalida(f"gatilho.para inválido: {g.get('para')} (use {sorted(ALVOS_GATILHO)})")
        if g.get("para") == "medicao":
            if g.get("campo") not in declaradas:
                raise Invalida(f"gatilho de medição aponta para '{g.get('campo')}', "
                               f"que não está em medicoes")
            if int(g.get("cada_dias", 0)) < 1:
                raise Invalida("gatilho de medição precisa de cada_dias >= 1")
        if g.get("tipo") not in TIPOS_GATILHO:
            raise Invalida(f"gatilho de tipo desconhecido: {g.get('tipo')} "
                           f"(a rotina só sabe {sorted(TIPOS_GATILHO)})")
        if g["tipo"] == "horario":
            if g.get("quando") == "auto":
                # gatilho aprendido: o horário sai do histórico de registros, e
                # 'quando_padrao' é o que vale enquanto não há amostra suficiente
                try:
                    hh, mm = g.get("quando_padrao", "").split(":")
                    assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
                except Exception:
                    raise Invalida("gatilho com quando=auto precisa de quando_padrao "
                                   "válido (o que fazer enquanto não aprendeu)")
                if int(g.get("minimo_amostras", 0)) < 2:
                    raise Invalida("gatilho aprendido precisa de minimo_amostras >= 2")
            else:
                try:
                    hh, mm = g["quando"].split(":")
                    assert 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
                except Exception:
                    raise Invalida(f"gatilho.quando inválido: {g.get('quando')}")
            dias = g.get("dias") or []
            if not dias or any(d not in range(1, 8) for d in dias):
                raise Invalida("gatilho.dias deve ser lista de 1..7 (1=segunda)")
        if g.get("msg") and g["msg"] not in spec["mensagens"]:
            raise Invalida(f"gatilho aponta para mensagem inexistente: {g['msg']}")

    gates = spec["gates"]
    jh = gates.get("janela_horas") or [0, 23]
    if len(jh) != 2 or not (0 <= jh[0] <= jh[1] <= 23):
        raise Invalida(f"gates.janela_horas inválida: {jh}")
    if int(gates.get("max_msgs_dia", 1)) < 1:
        raise Invalida("gates.max_msgs_dia deve ser >= 1")

    for c in spec["coleta"]:
        if "campo" not in c or "tipo" not in c:
            raise Invalida(f"item de coleta sem campo/tipo: {c}")
        if c.get("agregacao") and c["agregacao"] not in AGREGACOES:
            raise Invalida(f"agregacao inválida em {c['campo']}: {c['agregacao']}")
    return True


def hash_spec(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def salvar_nova_versao(con, spec_nova, autor, motivo=""):
    """Grava uma versão nova: arquivo corrente + cópia imutável vN.json + linha
    do tempo no banco. A versão anterior é fechada com desfecho — sem isso não dá
    para perguntar depois 'a v3 funcionou melhor que a v2?'."""
    validar(spec_nova)
    habito = spec_nova["habito"]
    hoje = R.hoje()
    ant = con.execute("""SELECT versao FROM estrategias WHERE habito=? AND ativa_ate IS NULL
                         ORDER BY versao DESC LIMIT 1""", (habito,)).fetchone()
    if ant:
        con.execute("UPDATE estrategias SET ativa_ate=?, desfecho=? WHERE habito=? AND versao=?",
                    (hoje, spec_nova.get("desfecho_anterior") or "substituida",
                     habito, ant[0]))
    spec_nova.pop("desfecho_anterior", None)
    txt = json.dumps(spec_nova, ensure_ascii=False, indent=2) + "\n"
    os.makedirs(os.path.join(EST, habito), exist_ok=True)
    open(caminho(habito), "w").write(txt)
    open(os.path.join(EST, habito, f"v{spec_nova['versao']}.json"), "w").write(txt)
    con.execute("""INSERT OR REPLACE INTO estrategias
                   (habito, versao, ativa_de, ativa_ate, arquivo, hash, autor, hipotese)
                   VALUES (?,?,?,NULL,?,?,?,?)""",
                (habito, spec_nova["versao"], hoje,
                 os.path.relpath(caminho(habito), RAIZ), hash_spec(spec_nova),
                 autor, spec_nova.get("hipotese")))
    R.grava_evento(con, habito, "estrategia_ativada", autor, hoje,
                   {"versao": spec_nova["versao"], "motivo": motivo,
                    "hipotese": spec_nova.get("hipotese"),
                    "revisar_em": spec_nova["horizonte"].get("revisar_em")})
    con.commit()
    return spec_nova["versao"]


def proxima_revisao(spec, a_partir=None):
    """Data da próxima revisão respeitando o dwell mínimo: estratégia nova não
    pode ser julgada antes de ter tido chance de pegar."""
    base = date.fromisoformat(a_partir or R.hoje())
    semanas = max(1, int(spec["horizonte"].get("dwell_min_semanas", 2)))
    d = base + timedelta(weeks=semanas)
    return (d + timedelta(days=(6 - d.weekday()))).isoformat()   # domingo seguinte


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ativas"
    if cmd == "ativas":
        con = R.conectar()
        for h in listar():
            s = carregar(h)
            ok = "ok"
            try:
                validar(s)
            except Invalida as e:
                ok = f"INVÁLIDA: {e}"
            print(f"{h}\tv{s['versao']}\t{s['estado']}\t"
                  f"revisar_em={s['horizonte'].get('revisar_em')}\t{ok}")
        return
    habito = sys.argv[2]
    if cmd == "validar":
        try:
            validar(carregar(habito))
            print(f"{habito}: spec válida")
        except Invalida as e:
            sys.exit(f"{habito}: {e}")
    elif cmd == "mostrar":
        print(json.dumps(carregar(habito), ensure_ascii=False, indent=2))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
