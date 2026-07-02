#!/usr/bin/env python3
"""gcal.py — cliente Google Calendar (OAuth2) do PIrrai, em Python puro (sem libs externas).

Escrita REAL na agenda do Google (criar/editar/excluir eventos), complementando o
agenda.py (que só lê iCal + Todoist). Fluxo OAuth "Desktop app" com colagem manual
do código (serve em servidor headless). Refresh token guardado em gcal_token.json.

Config em gcal.env:
  GCAL_CLIENT_ID=...
  GCAL_CLIENT_SECRET=...
  GCAL_CALENDAR_ID=rodrigor@dcx.ufpb.br   # ou 'primary'

Comandos:
  auth                          autoriza uma vez (imprime URL, você cola o code)
  list [dias]                   lista próximos eventos (teste de leitura)
  add "<título>" "<AAAA-MM-DD HH:MM>" [dur_min] [--desc "texto"]   cria evento
  del <eventId>                 exclui evento
  whoami                        mostra a conta/calendário autorizado
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(ROOT, "gcal_token.json")
TZ = ZoneInfo("America/Recife")
SCOPE = "https://www.googleapis.com/auth/calendar.events"
REDIRECT = "http://localhost"          # Desktop app: loopback (nada precisa escutar)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"

def _env(key, default=""):
    try:
        for ln in open(os.path.join(ROOT, "gcal.env"), encoding="utf-8"):
            ln = ln.strip()
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get(key, default)

def _post_form(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ERRO HTTP {e.code}: {e.read().decode(errors='replace')}")

def _save_token(d):
    json.dump(d, open(TOKEN_FILE, "w"))
    os.chmod(TOKEN_FILE, 0o600)

def cmd_auth():
    cid, secret = _env("GCAL_CLIENT_ID"), _env("GCAL_CLIENT_SECRET")
    if not cid or not secret:
        raise SystemExit("Configure GCAL_CLIENT_ID e GCAL_CLIENT_SECRET em gcal.env primeiro.")
    params = {"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
              "scope": SCOPE, "access_type": "offline", "prompt": "consent"}
    print("1) Abra esta URL no navegador (logado na conta da agenda) e autorize:\n")
    print("   " + AUTH_URL + "?" + urllib.parse.urlencode(params) + "\n")
    print("2) Vai redirecionar para http://localhost/?code=... (a página não carrega — tudo bem).")
    print("   Copie o valor de 'code' (ou cole a URL inteira) e cole aqui:\n")
    raw = input("code> ").strip()
    if "code=" in raw:                                  # colou a URL inteira
        raw = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("code", [""])[0]
    tok = _post_form(TOKEN_URL, {"code": raw, "client_id": cid, "client_secret": secret,
                                 "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    if "refresh_token" not in tok:
        raise SystemExit(f"Sem refresh_token na resposta (tente de novo com prompt=consent): {tok}")
    _save_token({"refresh_token": tok["refresh_token"],
                 "access_token": tok.get("access_token"),
                 "expiry": time.time() + tok.get("expires_in", 0) - 60})
    print("\nOK! Autorizado. Token salvo em gcal_token.json (chmod 600).")

def _access_token():
    if not os.path.exists(TOKEN_FILE):
        raise SystemExit("Não autorizado ainda. Rode: gcal.sh auth")
    t = json.load(open(TOKEN_FILE))
    if t.get("access_token") and t.get("expiry", 0) > time.time():
        return t["access_token"]
    tok = _post_form(TOKEN_URL, {"client_id": _env("GCAL_CLIENT_ID"),
                                 "client_secret": _env("GCAL_CLIENT_SECRET"),
                                 "refresh_token": t["refresh_token"], "grant_type": "refresh_token"})
    t["access_token"] = tok["access_token"]
    t["expiry"] = time.time() + tok.get("expires_in", 0) - 60
    _save_token(t)
    return t["access_token"]

def _api(method, path, params=None, body=None):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {_access_token()}",
                                          "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=30).read()
        return json.loads(r) if r else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"ERRO API {e.code}: {e.read().decode(errors='replace')}")

def _cal():
    return urllib.parse.quote(_env("GCAL_CALENDAR_ID", "primary"))

def cmd_list(days=7):
    now = datetime.now(TZ)
    ev = _api("GET", f"/calendars/{_cal()}/events",
              {"timeMin": now.isoformat(), "timeMax": (now + timedelta(days=days)).isoformat(),
               "singleEvents": "true", "orderBy": "startTime", "maxResults": 30})
    items = ev.get("items", [])
    print(f"📅 Próximos {days} dias ({len(items)} eventos):")
    for e in items:
        s = e["start"].get("dateTime", e["start"].get("date"))
        print(f"  • {s}  {e.get('summary','(sem título)')}  [{e['id']}]")

def cmd_add(args):
    desc = ""
    if "--desc" in args:
        i = args.index("--desc"); desc = args[i + 1] if i + 1 < len(args) else ""; args = args[:i] + args[i + 2:]
    if len(args) < 2:
        raise SystemExit('uso: add "<título>" "<AAAA-MM-DD HH:MM>" [dur_min]')
    title, when = args[0], args[1]
    dur = int(args[2]) if len(args) > 2 else 60
    start = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    end = start + timedelta(minutes=dur)
    body = {"summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": "America/Recife"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/Recife"}}
    if desc:
        body["description"] = desc
    e = _api("POST", f"/calendars/{_cal()}/events", body=body)
    print(f"OK: '{e.get('summary')}' {start:%d/%m %H:%M}–{end:%H:%M} criado. id={e['id']}")
    if e.get("htmlLink"):
        print(e["htmlLink"])

def cmd_del(eid):
    _api("DELETE", f"/calendars/{_cal()}/events/{urllib.parse.quote(eid)}")
    print(f"OK: evento {eid} excluído.")

def cmd_whoami():
    c = _api("GET", f"/calendars/{_cal()}")
    print(f"Calendário: {c.get('summary')} ({c.get('id')}) — TZ {c.get('timeZone')}")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "auth": cmd_auth()
    elif cmd == "list": cmd_list(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
    elif cmd == "add": cmd_add(sys.argv[2:])
    elif cmd == "del": cmd_del(sys.argv[2])
    elif cmd == "whoami": cmd_whoami()
    else: print(__doc__); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
