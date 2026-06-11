#!/usr/bin/env python3
"""finance_user.py — gerencia usuários do web de finanças (hash werkzeug).
Uso: finance_user.py set <user> [role admin|editor] [senha]   |   list   |   del <user>"""
import sys, json, os, secrets
from werkzeug.security import generate_password_hash
DIR = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(DIR, "finance_users.json")

def load():
    try:
        with open(F) as fh: return json.load(fh)
    except Exception: return {}

def save(d):
    with open(F, "w") as fh: json.dump(d, fh, indent=2, ensure_ascii=False)
    os.chmod(F, 0o600)

cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
if cmd == "set":
    user = sys.argv[2]
    role = sys.argv[3] if len(sys.argv) > 3 else "editor"
    pw   = sys.argv[4] if len(sys.argv) > 4 else secrets.token_urlsafe(9)
    d = load(); d[user] = {"hash": generate_password_hash(pw), "role": role}; save(d)
    print(f"OK — {user} ({role}) · senha: {pw}")
elif cmd == "del":
    d = load(); d.pop(sys.argv[2], None); save(d); print("OK removido:", sys.argv[2])
else:
    for u, v in load().items(): print(u, v.get("role"))
