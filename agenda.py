#!/usr/bin/env python3
"""agenda.py — módulo de agenda do PIrrai.

Lê o iCal (somente leitura) do Google Calendar pessoal (DCX) + tarefas com hora do
Todoist (API REST), unifica numa visão de agenda e acha horários livres.
Criar "evento" = criar tarefa no Todoist com data/hora (todoist.sh add) — não há
escrita via iCal. Sem libs externas além de python-dateutil.

Comandos:
  fetch                      baixa o iCal p/ cache (rodar via cron ~30 min)
  today                      agenda de hoje (eventos + tarefas)
  week [N]                   próximos N dias (padrão 7)
  free <min> [dias] [hi] [hf]  janelas livres de >=<min> minutos (padrão: 7 dias, 6h-22h)
  new "<título>" "<início>" ["<fim>"] [--local X] [--desc Y] [--convida a@x,b@y]
                             cria evento no Google Calendar (escrita via OAuth)
  edit <id> [--titulo X] [--inicio ...] [--fim ...] [--local X] [--desc Y] [--convida ...]
  cancel <id>                cancela evento (notifica convidados)
"""
import os, sys, json, re, urllib.request, urllib.parse, urllib.error, datetime as dt
from datetime import datetime, timedelta, time, timezone, date
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr
from dateutil import parser as dtparser

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state")
CACHE = os.path.join(STATE, "agenda_dcx.ics")
TZ = ZoneInfo("America/Recife")
UTC = timezone.utc
DEFAULT_TASK_MIN = 30          # duração assumida p/ tarefa Todoist com hora sem duração definida
DAY_START, DAY_END = 6, 22     # janela padrão p/ busca de slot livre

def _load_env(path, key):
    try:
        for ln in open(os.path.join(ROOT, path), encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get(key, "")

# ---------------- fetch / cache ----------------
def fetch():
    url = _load_env("agenda.env", "AGENDA_ICAL_DCX")
    if not url:
        print("ERRO: AGENDA_ICAL_DCX não configurado em agenda.env", file=sys.stderr); return 2
    os.makedirs(STATE, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "PIrrai-agenda/1.0"})
    data = urllib.request.urlopen(req, timeout=30).read()
    if b"BEGIN:VCALENDAR" not in data[:200]:
        print("ERRO: resposta não parece iCal", file=sys.stderr); return 1
    tmp = CACHE + ".tmp"
    open(tmp, "wb").write(data)
    os.replace(tmp, CACHE)
    n = data.count(b"BEGIN:VEVENT")
    print(f"ok: {len(data)} bytes, {n} VEVENT -> {CACHE}")
    return 0

def _ics_text():
    if not os.path.exists(CACHE):
        if fetch() != 0:
            raise SystemExit("sem cache e fetch falhou")
    raw = open(CACHE, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
    # RFC5545: linha continuada começa com espaço/tab
    import re
    return re.sub(r"\n[ \t]", "", raw)

# ---------------- parsing iCal ----------------
def _split_prop(line):
    """'DTSTART;TZID=America/Recife:2022...' -> ('DTSTART', {'TZID':...}, '2022...')"""
    head, _, value = line.partition(":")
    name, *parts = head.split(";")
    params = {}
    for p in parts:
        k, _, v = p.partition("=")
        params[k.upper()] = v
    return name.upper(), params, value

def _parse_dt(value, params):
    """retorna (datetime_aware|date, all_day)."""
    if params.get("VALUE") == "DATE" or ("T" not in value and len(value) == 8):
        return datetime.strptime(value, "%Y%m%d").date(), True
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False
    base = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    try:
        return base.replace(tzinfo=ZoneInfo(tzid)) if tzid else base.replace(tzinfo=TZ), False
    except Exception:
        return base.replace(tzinfo=TZ), False

def _events(text):
    for blk in text.split("BEGIN:VEVENT")[1:]:
        blk = blk.split("END:VEVENT")[0]
        ev = {"rrule": None, "exdates": [], "summary": "(sem título)",
              "dtstart": None, "p_start": {}, "dtend": None, "p_end": {}}
        for ln in blk.split("\n"):
            if not ln or ":" not in ln:
                continue
            name, params, value = _split_prop(ln)
            if name == "DTSTART":
                ev["dtstart"], ev["p_start"] = value, params
            elif name == "DTEND":
                ev["dtend"], ev["p_end"] = value, params
            elif name == "RRULE":
                ev["rrule"] = value
            elif name == "EXDATE":
                ev["exdates"].extend(value.split(","))
            elif name == "SUMMARY":
                ev["summary"] = value.replace("\\,", ",").replace("\\n", " ").strip()
        if ev["dtstart"]:
            yield ev

def _to_utc(d):
    if isinstance(d, datetime):
        return d.astimezone(UTC)
    return datetime.combine(d, time(0), TZ).astimezone(UTC)

def occurrences(ev, ws, we):
    """ocorrências (start, end, all_day) do evento dentro de [ws, we] (aware)."""
    start, all_day = _parse_dt(ev["dtstart"], ev["p_start"])
    if ev["dtend"]:
        end, _ = _parse_dt(ev["dtend"], ev["p_end"])
    else:
        end = (start + timedelta(days=1)) if all_day else (start + timedelta(hours=1))
    out = []
    if not ev["rrule"]:
        s, e = _norm(start, all_day), _norm(end, all_day)
        if s < we and e > ws:
            out.append((s, e, all_day))
        return out
    # recorrente
    dur = _to_utc(end) - _to_utc(start)
    anchor = start if isinstance(start, datetime) else datetime.combine(start, time(0), TZ)
    try:
        rule = rrulestr(ev["rrule"], dtstart=anchor)
    except Exception:
        return out
    ex = {_to_utc(_parse_dt(x, {})[0]) for x in ev["exdates"]}
    for occ in rule.between(ws - dur, we, inc=True):
        if _to_utc(occ) in ex:
            continue
        s = occ if isinstance(start, datetime) else occ.date()
        e = (occ + dur)
        if all_day:
            e = (occ + dur).date() if not isinstance(start, datetime) else e
        s, e = _norm(s, all_day), _norm(e, all_day)
        if s < we and e > ws:
            out.append((s, e, all_day))
    return out

def _norm(d, all_day):
    """date/datetime -> datetime aware em TZ (para all-day usa 00:00 local)."""
    if isinstance(d, datetime):
        return d.astimezone(TZ)
    return datetime.combine(d, time(0), TZ)

def cal_events_ical(ws, we):
    """fallback offline: lê do cache iCal (state/agenda_dcx.ics)."""
    text = _ics_text()
    items = []
    for ev in _events(text):
        for s, e, ad in occurrences(ev, ws, we):
            items.append({"start": s, "end": e, "all_day": ad,
                          "summary": ev["summary"], "source": "cal"})
    return items

def cal_events_api(ws, we):
    """lê eventos via Google Calendar API (tempo real; recorrência expandida no servidor)."""
    items, page = [], None
    while True:
        params = {"timeMin": ws.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                  "timeMax": we.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": 2500}
        if page:
            params["pageToken"] = page
        r = _gcal("GET", "/calendars/primary/events", params=params)
        for it in r.get("items", []):
            if it.get("status") == "cancelled":
                continue
            s, e = it.get("start", {}), it.get("end", {})
            if "dateTime" in s:
                st = datetime.fromisoformat(s["dateTime"]).astimezone(TZ)
                en = datetime.fromisoformat(e.get("dateTime", s["dateTime"])).astimezone(TZ)
                ad = False
            else:
                st = _norm(date.fromisoformat(s["date"]), True)
                en = _norm(date.fromisoformat(e.get("date", s["date"])), True)
                ad = True
            items.append({"start": st, "end": en, "all_day": ad,
                          "summary": it.get("summary", "(sem título)"), "source": "cal",
                          "id": it.get("id")})
        page = r.get("nextPageToken")
        if not page:
            break
    return items

def cal_events(ws, we):
    """API (tempo real) com fallback pro cache iCal se a API/rede falhar."""
    try:
        return cal_events_api(ws, we)
    except Exception as e:
        print(f"(aviso: API Calendar indisponível, usando cache iCal: {e})", file=sys.stderr)
        return cal_events_ical(ws, we)

# ---------------- Todoist ----------------
def todoist_items(ws, we):
    token = _load_env("todoist.env", "TODOIST_TOKEN")
    if not token:
        return []
    url = "https://api.todoist.com/api/v1/tasks?limit=200"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"(aviso: Todoist indisponível: {e})", file=sys.stderr)
        return []
    out = []
    for t in data.get("results", []):
        due = t.get("due")
        if not due:
            continue
        val = due.get("datetime") or due.get("date") or ""   # v1: due.date pode ser date OU datetime
        if "T" in val:                                        # tarefa COM hora
            s = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=TZ)
            s = s.astimezone(TZ)
            dur = t.get("duration") or {}
            mins = dur.get("amount", DEFAULT_TASK_MIN) if dur.get("unit") == "minute" else DEFAULT_TASK_MIN
            e = s + timedelta(minutes=mins)
            ad = False
        else:                                                 # tarefa de dia (sem hora)
            s = _norm(date.fromisoformat(val), True)
            e = s + timedelta(days=1)
            ad = True
        if s < we and e > ws:
            out.append({"start": s, "end": e, "all_day": ad,
                        "summary": "✓ " + t.get("content", ""), "source": "todoist"})
    return out

# ---------------- Google Calendar (ESCRITA via OAuth) ----------------
GCAL_API = "https://www.googleapis.com/calendar/v3"
ACCESS_CACHE = os.path.join(STATE, "gcal_access.json")

def _gcal_token():
    """access token válido (refresh via refresh_token; cache em disco até expirar)."""
    try:
        ca = json.load(open(ACCESS_CACHE))
        if ca.get("exp", 0) > datetime.now(UTC).timestamp() + 60:
            return ca["access_token"]
    except Exception:
        pass
    rt = _load_env("agenda.env", "GCAL_REFRESH_TOKEN")
    if not rt:
        raise SystemExit("ERRO: GCAL_REFRESH_TOKEN ausente (rode o fluxo OAuth)")
    c = json.load(open(os.path.join(ROOT, "gcal_client.json")))["installed"]
    data = urllib.parse.urlencode({
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": rt, "grant_type": "refresh_token"}).encode()
    tok = json.load(urllib.request.urlopen(urllib.request.Request(c["token_uri"], data=data), timeout=20))
    os.makedirs(STATE, exist_ok=True)
    json.dump({"access_token": tok["access_token"],
               "exp": datetime.now(UTC).timestamp() + tok.get("expires_in", 3600)},
              open(ACCESS_CACHE, "w"))
    os.chmod(ACCESS_CACHE, 0o600)
    return tok["access_token"]

def _gcal(method, path, body=None, params=None):
    url = f"{GCAL_API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_gcal_token()}", "Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=25).read()
        return json.loads(resp) if resp else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Google Calendar {e.code}: {e.read().decode()[:300]}")

def _parse_when(s):
    """'2026-06-20 14h30' -> ({api start/end}, all_day, datetime). Aceita data BR e Xh/XhYY."""
    s = re.sub(r"(\d{1,2})h(\d{2})", r"\1:\2", s.strip())   # 14h30 -> 14:30
    s = re.sub(r"(\d{1,2})h\b", r"\1:00", s)                # 14h -> 14:00
    has_time = (":" in s) or ("T" in s)
    d = dtparser.parse(s, dayfirst=True, fuzzy=True)
    if has_time:
        if d.tzinfo is None:
            d = d.replace(tzinfo=TZ)
        return {"dateTime": d.isoformat(), "timeZone": "America/Recife"}, False, d
    return {"date": d.date().isoformat()}, True, d

def gcal_create(summary, inicio, fim=None, local=None, desc=None, convida=None):
    st, all_day, ds = _parse_when(inicio)
    if fim:
        en, _, _ = _parse_when(fim)
    elif all_day:
        en = {"date": (ds.date() + timedelta(days=1)).isoformat()}
    else:
        en = {"dateTime": (ds + timedelta(hours=1)).isoformat(), "timeZone": "America/Recife"}
    body = {"summary": summary, "start": st, "end": en}
    if local: body["location"] = local
    if desc: body["description"] = desc
    if convida:
        body["attendees"] = [{"email": e.strip()} for e in convida.split(",") if e.strip()]
    params = {"sendUpdates": "all"} if convida else None
    ev = _gcal("POST", "/calendars/primary/events", body, params)
    return ev

def gcal_update(eid, summary=None, inicio=None, fim=None, local=None, desc=None, convida=None):
    body = {}
    if summary is not None: body["summary"] = summary
    if inicio: body["start"], _, _ = _parse_when(inicio)
    if fim:    body["end"], _, _ = _parse_when(fim)
    if local is not None: body["location"] = local
    if desc is not None:  body["description"] = desc
    if convida is not None:
        body["attendees"] = [{"email": e.strip()} for e in convida.split(",") if e.strip()]
    params = {"sendUpdates": "all"} if convida else None
    return _gcal("PATCH", f"/calendars/primary/events/{eid}", body, params)

def gcal_delete(eid):
    _gcal("DELETE", f"/calendars/primary/events/{eid}", params={"sendUpdates": "all"})
    return True

# ---------------- agenda / livre ----------------
def agenda(ws, we):
    items = cal_events(ws, we) + todoist_items(ws, we)
    items.sort(key=lambda x: (x["start"], not x["all_day"]))
    return items

def busy_blocks(ws, we):
    """blocos ocupados (eventos e tarefas COM hora; all-day não bloqueia slot)."""
    b = [(max(i["start"], ws), min(i["end"], we))
         for i in agenda(ws, we) if not i["all_day"]]
    b = [(s, e) for s, e in b if e > s]
    b.sort()
    merged = []
    for s, e in b:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged

def free_slots(minutes, days, h0, h1):
    now = datetime.now(TZ)
    need = timedelta(minutes=minutes)
    out = []
    for d in range(days):
        day = (now + timedelta(days=d)).date()
        ws = datetime.combine(day, time(h0), TZ)
        we = datetime.combine(day, time(h1), TZ)
        if d == 0 and now > ws:
            ws = now.replace(minute=(now.minute // 5 + 1) * 5 % 60,
                             second=0, microsecond=0)
            if now.minute // 5 + 1 >= 12:
                ws = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        if ws >= we:
            continue
        cur = ws
        for bs, be in busy_blocks(ws, we):
            if bs > cur and bs - cur >= need:
                out.append((cur, bs))
            cur = max(cur, be)
        if we - cur >= need:
            out.append((cur, we))
    return out

# ---------------- CLI / formatação ----------------
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
def _fmt_day(d):
    return f"{DIAS[d.weekday()]} {d.day:02d}/{d.month:02d}"

def _print_agenda(items, header):
    print(header)
    if not items:
        print("  (nada)"); return
    last = None
    for i in items:
        dlabel = _fmt_day(i["start"])
        if dlabel != last:
            print(f"\n{dlabel}:"); last = dlabel
        eid = f"  [#{i['id']}]" if i.get("id") else ""
        if i["all_day"]:
            print(f"  • dia todo — {i['summary']}{eid}")
        else:
            print(f"  • {i['start']:%H:%M}–{i['end']:%H:%M} {i['summary']}{eid}")

def _split_opts(args):
    """separa posicionais de flags --chave valor. Ex.: ['x','--local','Sala'] -> (['x'],{'local':'Sala'})"""
    pos, opt, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            opt[a[2:]] = args[i + 1] if i + 1 < len(args) else ""
            i += 2
        else:
            pos.append(a); i += 1
    return pos, opt

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    now = datetime.now(TZ)
    if cmd == "fetch":
        return fetch()
    if cmd == "today":
        ws = datetime.combine(now.date(), time(0), TZ)
        we = ws + timedelta(days=1)
        _print_agenda(agenda(ws, we), f"📅 Agenda de hoje ({_fmt_day(now)})")
    elif cmd == "week":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        ws = datetime.combine(now.date(), time(0), TZ)
        we = ws + timedelta(days=n)
        _print_agenda(agenda(ws, we), f"📅 Próximos {n} dias")
    elif cmd == "free":
        mins = int(sys.argv[2]) if len(sys.argv) > 2 else 40
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
        h0 = int(sys.argv[4]) if len(sys.argv) > 4 else DAY_START
        h1 = int(sys.argv[5]) if len(sys.argv) > 5 else DAY_END
        slots = free_slots(mins, days, h0, h1)
        print(f"🕳️ Janelas livres de ≥{mins}min ({h0}h–{h1}h, {days} dias):")
        if not slots:
            print("  (nenhuma)"); return 0
        last = None
        for s, e in slots[:15]:
            dlabel = _fmt_day(s)
            if dlabel != last:
                print(f"\n{dlabel}:"); last = dlabel
            print(f"  • {s:%H:%M}–{e:%H:%M} ({int((e-s).total_seconds()//60)}min)")
    elif cmd == "new":
        pos, opt = _split_opts(sys.argv[2:])
        if len(pos) < 2:
            print('uso: agenda.sh new "<título>" "<início>" ["<fim>"] [--local X] [--desc Y] [--convida a@x,b@y]')
            return 1
        ev = gcal_create(pos[0], pos[1], pos[2] if len(pos) > 2 else None,
                         opt.get("local"), opt.get("desc"), opt.get("convida"))
        st = ev.get("start", {})
        print(f"✅ Criado: {ev.get('summary')} — {st.get('dateTime') or st.get('date')}")
        print(f"   id: {ev.get('id')}")
        if ev.get("htmlLink"): print(f"   {ev['htmlLink']}")
    elif cmd == "edit":
        pos, opt = _split_opts(sys.argv[2:])
        if not pos:
            print('uso: agenda.sh edit <id> [--titulo X] [--inicio ...] [--fim ...] [--local X] [--desc Y] [--convida a@x]')
            return 1
        ev = gcal_update(pos[0], opt.get("titulo"), opt.get("inicio"), opt.get("fim"),
                         opt.get("local"), opt.get("desc"), opt.get("convida"))
        st = ev.get("start", {})
        print(f"✏️ Atualizado: {ev.get('summary')} — {st.get('dateTime') or st.get('date')} (id {ev.get('id')})")
    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print("uso: agenda.sh cancel <id>"); return 1
        gcal_delete(sys.argv[2])
        print(f"🗑️ Evento {sys.argv[2]} cancelado (convidados notificados).")
    else:
        print(__doc__)
        return 1
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except (RuntimeError, urllib.error.URLError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(1)
