#!/usr/bin/env python3
"""registro.py — o único módulo que escreve no banco de hábitos.

Contrato (ver a arquitetura em 4 módulos):
  - sensores e rotina GRAVAM eventos aqui e nunca tocam no banco direto;
  - rotina e coach LEEM daqui (views), em vez de recalcular estado;
  - `eventos` é append-only: nada de UPDATE/DELETE em fato registrado. Corrigir
    é registrar um evento novo, não reescrever o passado.

Saída sempre em JSON no stdout (quem formata para humano é o habitos.sh).

Uso:
  registro.py init
  registro.py sessao   --habito HABITO [--data AAAA-MM-DD] [--nota "..."]
                       [--metrica campo=valor[:unidade[:classe[:agregacao]]]]...
  registro.py falha    --habito HABITO [--data ...] [--obstaculo MOTIVO] [--nota ...]
  registro.py evento   --habito HABITO --tipo lembrete [--payload '{}']
  registro.py metrica  --habito HABITO --campo CAMPO --valor N [--unidade U]
                       [--classe resultado] [--agregacao ultimo] [--data ...]
  registro.py semana   [--habito HABITO] [--n 12]
  registro.py eventos  [--habito HABITO] [--n 30] [--tipo sessao]
  registro.py consulta "SELECT ..."      (somente leitura)
"""
import argparse, json, os, sqlite3, sys
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("HABITOS_DB", os.path.join(os.path.dirname(DIR), "state", "habitos.db"))
SCHEMA = os.path.join(DIR, "schema.sql")


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hoje():
    return datetime.now().strftime("%Y-%m-%d")


def carregar_spec(habito):
    """Lê a estratégia sem importar o módulo (evita ciclo): só o que o registro
    precisa saber para derivar."""
    fp = os.path.join(DIR, "estrategias", f"{habito}.json")
    try:
        return json.load(open(fp))
    except (OSError, json.JSONDecodeError):
        return None


def conectar(criar=True):
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    novo = not os.path.exists(DB)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if criar and (novo or con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='eventos'"
    ).fetchone()[0] == 0):
        con.executescript(open(SCHEMA).read())
        con.commit()
    return con


def valida_data(d):
    """Aceita só AAAA-MM-DD: data torta vira semana torta em todas as views."""
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"data inválida (esperado AAAA-MM-DD): {d}")
    return d


def grava_evento(con, habito, tipo, origem, data=None, payload=None, ts=None):
    data = valida_data(data or hoje())
    cur = con.execute(
        "INSERT INTO eventos (ts, data, habito, tipo, origem, payload) VALUES (?,?,?,?,?,?)",
        (ts or agora(), data, habito, tipo, origem, json.dumps(payload or {}, ensure_ascii=False)))
    return cur.lastrowid


def grava_metrica(con, habito, campo, valor, unidade=None, classe="contexto",
                  fonte="manual", data=None, evento_id=None, ts=None,
                  agregacao="soma"):
    data = valida_data(data or hoje())
    num, txt = None, None
    try:
        num = float(valor)
    except (TypeError, ValueError):
        txt = str(valor)
    cur = con.execute(
        """INSERT INTO metricas (ts, data, habito, campo, valor_num, valor_txt,
                                 unidade, classe, agregacao, fonte, evento_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (ts or agora(), data, habito, campo, num, txt, unidade, classe, agregacao,
         fonte, evento_id))
    return cur.lastrowid


def condicao_ok(cond, valor):
    """Operadores da linguagem fechada de derivadas. Sem eval, sem código do
    domínio: o núcleo só compara números que a estratégia declarou."""
    if valor is None:
        return False
    if "entre" in cond:
        a, b = cond["entre"]
        if not (a <= valor <= b):
            return False
    if "min" in cond and valor < cond["min"]:
        return False
    if "max" in cond and valor > cond["max"]:
        return False
    if "igual" in cond and valor != cond["igual"]:
        return False
    return True


def aplicar_derivadas(con, spec, habito, data, evento_id, valores, fonte="derivada"):
    """Calcula as métricas derivadas de uma sessão a partir da spec.

    A estratégia declara algo como "o valor deste campo só conta quando aquele
    outro campo estiver nesta faixa". O núcleo não sabe o que os campos
    significam: só sabe aplicar a condição declarada. Se a regra mudar, o dado
    derivado é reconstruível por definição (habitos.sh recalcular).
    """
    criadas = []
    for d in spec.get("derivadas", []):
        base = valores.get(d["de"])
        if base is None:
            continue
        if not all(condicao_ok(cond, valores.get(campo))
                   for campo, cond in (d.get("quando") or {}).items()):
            continue
        criadas.append(grava_metrica(
            con, habito, d["campo"], base, d.get("unidade"),
            d.get("classe", "resultado"), fonte, data, evento_id,
            agregacao=d.get("agregacao", "soma")))
    return criadas


def parse_metricas(itens):
    """campo=valor[:unidade[:classe]] -> lista de dicts."""
    out = []
    for it in itens or []:
        if "=" not in it:
            sys.exit(f"métrica sem '=': {it}")
        campo, resto = it.split("=", 1)
        partes = resto.split(":")
        out.append({"campo": campo, "valor": partes[0],
                    "unidade": partes[1] if len(partes) > 1 and partes[1] else None,
                    "classe": partes[2] if len(partes) > 2 and partes[2] else "contexto",
                    "agregacao": partes[3] if len(partes) > 3 and partes[3] else "soma"})
    return out


def cmd_sessao(a, con):
    metricas = parse_metricas(a.metrica)
    payload = {"nota": a.nota} if a.nota else {}
    if a.payload:
        payload.update(json.loads(a.payload))
    eid = grava_evento(con, a.habito, "sessao", a.origem, a.data, payload)
    ids = [grava_metrica(con, a.habito, m["campo"], m["valor"], m["unidade"],
                         m["classe"], a.origem, a.data, eid, agregacao=m["agregacao"])
           for m in metricas]
    derivadas = []
    spec = carregar_spec(a.habito)
    if spec:
        valores = {}
        for m in metricas:
            try:
                valores[m["campo"]] = float(m["valor"])
            except (TypeError, ValueError):
                pass
        derivadas = aplicar_derivadas(con, spec, a.habito, a.data or hoje(), eid, valores)
    con.commit()
    return {"evento": eid, "metricas": ids, "derivadas": derivadas,
            "data": a.data or hoje()}


def cmd_falha(a, con):
    """Falha é o que a pessoa DISSE que não fez, com o motivo. Silêncio não é
    falha — quem não respondeu vira evento 'silencio', registrado pela rotina."""
    payload = {}
    if a.obstaculo:
        payload["obstaculo"] = a.obstaculo
    if a.nota:
        payload["nota"] = a.nota
    eid = grava_evento(con, a.habito, "falha", a.origem, a.data, payload)
    con.commit()
    return {"evento": eid, "data": a.data or hoje()}


def cmd_evento(a, con):
    eid = grava_evento(con, a.habito, a.tipo, a.origem, a.data,
                       json.loads(a.payload) if a.payload else {})
    con.commit()
    return {"evento": eid}


def cmd_metrica(a, con):
    mid = grava_metrica(con, a.habito, a.campo, a.valor, a.unidade, a.classe,
                        a.origem, a.data, agregacao=a.agregacao)
    con.commit()
    return {"metrica": mid}


def semanas_recentes(n):
    """Série CONTÍNUA das últimas n semanas (segunda-feira de cada uma).
    Semana sem nenhum registro precisa aparecer: 'zero sessões' é justamente a
    informação que o coach e a pessoa precisam ver — o desenho velho só listava
    semanas com log e por isso a semana corrente vazia sumia da tela."""
    hoje_d = datetime.now().date()
    segunda = hoje_d - timedelta(days=hoje_d.weekday())
    return [(segunda - timedelta(weeks=i)).isoformat() for i in range(n)]


def cmd_semana(a, con):
    """Resumo por semana: sessões + métricas (já agregadas) + obstáculos."""
    args = [a.habito] if a.habito else []
    if a.habito:
        habitos = [a.habito]
    else:
        habitos = [r[0] for r in con.execute(
            "SELECT DISTINCT habito FROM eventos ORDER BY habito").fetchall()]
    janela = semanas_recentes(a.n)
    marks = ",".join("?" * len(janela))
    sess = {(r["habito"], r["semana"]): dict(r) for r in con.execute(
        f"""SELECT * FROM v_sessoes_semanais WHERE semana IN ({marks})
            {'AND habito = ?' if a.habito else ''}""", janela + args).fetchall()}
    semanas = []
    for sem in janela:
        for h in habitos:
            base = sess.get((h, sem), {"habito": h, "semana": sem, "sessoes": 0,
                                       "registros": 0})
            semanas.append(dict(base))
    mets = con.execute(f"""SELECT * FROM v_metricas_semanais
                           WHERE semana IN ({marks}) {'AND habito = ?' if a.habito else ''}
                           ORDER BY semana DESC""", janela + args).fetchall()
    obst = con.execute(f"""SELECT * FROM v_obstaculos_semanais
                           WHERE semana IN ({marks}) {'AND habito = ?' if a.habito else ''}
                           ORDER BY semana DESC""", janela + args).fetchall()
    for s in semanas:
        s["metricas"] = [dict(m) for m in mets
                         if m["semana"] == s["semana"] and m["habito"] == s["habito"]]
        s["obstaculos"] = [dict(o) for o in obst
                           if o["semana"] == s["semana"] and o["habito"] == s["habito"]]
    return semanas


def cmd_eventos(a, con):
    cond, args = [], []
    if a.habito:
        cond.append("habito = ?"); args.append(a.habito)
    if a.tipo:
        cond.append("tipo = ?"); args.append(a.tipo)
    where = ("WHERE " + " AND ".join(cond)) if cond else ""
    rows = con.execute(f"""SELECT id, ts, data, semana, habito, tipo, origem, payload
                           FROM v_eventos {where} ORDER BY data DESC, id DESC LIMIT ?""",
                       args + [a.n]).fetchall()
    return [dict(r) for r in rows]


def cmd_recalcular(a, con):
    """Refaz as métricas derivadas de todas as sessões do hábito. Dado derivado
    é reconstruível: se a regra na estratégia mudar, isto realinha o passado sem
    tocar nos fatos crus (que continuam intocados em `eventos`)."""
    spec = carregar_spec(a.habito)
    if not spec:
        sys.exit(f"sem estratégia para '{a.habito}'")
    campos = [d["campo"] for d in spec.get("derivadas", [])]
    if not campos:
        return {"derivadas": 0, "aviso": "a estratégia não declara nenhuma derivada"}
    marks = ",".join("?" * len(campos))
    apagadas = con.execute(
        f"DELETE FROM metricas WHERE habito=? AND fonte='derivada' AND campo IN ({marks})",
        [a.habito] + campos).rowcount
    criadas = 0
    for ev in con.execute("""SELECT id, data FROM eventos WHERE habito=? AND tipo='sessao'""",
                          (a.habito,)).fetchall():
        valores = {r["campo"]: r["valor_num"] for r in con.execute(
            "SELECT campo, valor_num FROM metricas WHERE evento_id=?", (ev["id"],))}
        criadas += len(aplicar_derivadas(con, spec, a.habito, ev["data"], ev["id"], valores))
    con.commit()
    return {"apagadas": apagadas, "criadas": criadas, "campos": campos}


def cmd_consulta(a, con):
    sql = a.sql.strip()
    # Guard-rail: o coach vai consultar por aqui; leitura é tudo que ele precisa.
    if not sql.lower().startswith(("select", "with")):
        sys.exit("consulta: só SELECT/WITH são permitidos")
    return [dict(r) for r in con.execute(sql).fetchall()]


def main():
    p = argparse.ArgumentParser(description="registro de hábitos (eventos + métricas)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def comum(sp, habito=True):
        if habito:
            sp.add_argument("--habito", required=True)
        sp.add_argument("--data", help="dia a que o fato se refere (padrão: hoje)")
        sp.add_argument("--origem", default="manual")

    sp = sub.add_parser("init", help="cria o banco e as views")

    sp = sub.add_parser("sessao", help="registra que fez, com as métricas")
    comum(sp); sp.add_argument("--metrica", action="append",
                               help="campo=valor[:unidade[:classe]] (repetível)")
    sp.add_argument("--nota"); sp.add_argument("--payload")

    sp = sub.add_parser("falha", help="registra que NÃO fez, com o motivo")
    comum(sp); sp.add_argument("--obstaculo"); sp.add_argument("--nota")

    sp = sub.add_parser("evento", help="evento cru (rotina/coach)")
    comum(sp); sp.add_argument("--tipo", required=True); sp.add_argument("--payload")

    sp = sub.add_parser("metrica", help="métrica solta, fora de uma sessão")
    comum(sp); sp.add_argument("--campo", required=True); sp.add_argument("--valor", required=True)
    sp.add_argument("--unidade"); sp.add_argument("--classe", default="contexto")
    sp.add_argument("--agregacao", default="soma", choices=["soma", "media", "ultimo"])

    sp = sub.add_parser("semana", help="resumo semanal"); sp.add_argument("--habito")
    sp.add_argument("--n", type=int, default=12)

    sp = sub.add_parser("eventos", help="últimos eventos"); sp.add_argument("--habito")
    sp.add_argument("--tipo"); sp.add_argument("--n", type=int, default=30)

    sp = sub.add_parser("consulta", help="SELECT livre (leitura)"); sp.add_argument("sql")

    sp = sub.add_parser("recalcular", help="refaz as métricas derivadas do hábito")
    sp.add_argument("--habito", required=True)

    a = p.parse_args()
    con = conectar()
    fn = {"init": lambda a, c: {"db": DB, "ok": True},
          "sessao": cmd_sessao, "falha": cmd_falha, "evento": cmd_evento,
          "metrica": cmd_metrica, "semana": cmd_semana, "eventos": cmd_eventos,
          "consulta": cmd_consulta, "recalcular": cmd_recalcular}[a.cmd]
    print(json.dumps(fn(a, con), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
