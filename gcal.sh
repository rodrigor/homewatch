#!/bin/bash
# gcal.sh — wrapper do cliente Google Calendar (OAuth) do PIrrai (lógica em gcal.py)
# Uso: gcal.sh {auth|whoami|list [dias]|add "<título>" "<AAAA-MM-DD HH:MM>" [dur_min] [--desc "txt"]|del <id>}
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/gcal.py" "$@"
