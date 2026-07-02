#!/bin/bash
# agenda.sh — wrapper do módulo de agenda do PIrrai (lógica em agenda.py)
# Uso: agenda.sh {fetch|today|week [N]|free <min> [dias] [hi] [hf]}
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$DIR/agenda.py" "$@"
