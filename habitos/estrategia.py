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
ESTADOS = {"ativo", "pausado", "suspenso"}
AGREGACOES = {"soma", "media", "ultimo"}
# Primitivas que a rotina sabe executar. Estratégia que peça outra coisa é
# recusada na validação — é assim que o coach fica preso a mexer em parâmetros.
CAMPOS_OBRIGATORIOS = {"habito", "versao", "estado", "criterio_sucesso",
                       "horizonte", "gatilhos", "coleta", "mensagens", "gates"}


class Invalida(Exception):
    pass


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
    if cs.get("resultado") and "metrica" not in cs["resultado"]:
        raise Invalida("criterio_sucesso.resultado precisa de 'metrica'")

    hz = spec["horizonte"]
    if hz.get("revisar_em"):
        try:
            date.fromisoformat(hz["revisar_em"])
        except ValueError:
            raise Invalida(f"horizonte.revisar_em inválido: {hz['revisar_em']}")
    if int(hz.get("dwell_min_semanas", 0)) < 1:
        raise Invalida("horizonte.dwell_min_semanas deve ser >= 1: estratégia que "
                       "pode ser trocada a qualquer momento nunca é testada")

    for g in spec["gatilhos"]:
        if g.get("tipo") not in TIPOS_GATILHO:
            raise Invalida(f"gatilho de tipo desconhecido: {g.get('tipo')} "
                           f"(a rotina só sabe {sorted(TIPOS_GATILHO)})")
        if g["tipo"] == "horario":
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
