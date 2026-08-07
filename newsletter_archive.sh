#!/bin/bash
# newsletter_archive.sh — arquiva newsletters já "consumidas" (mais de N dias
# em inbox/dropped/) para arquivo/newsletters/AAAA-MM/, mantendo o dropped/
# limpo. Identifica pelo frontmatter (tipo: newsletter). Roda semanal via cron.
set -euo pipefail

VAULT="/home/rodrigor/vault-home"
DROPPED="$VAULT/inbox/dropped"
ARCHIVE_BASE="$VAULT/arquivo/newsletters"
MIN_AGE_DAYS=3

cd "$DROPPED"
moved=0
list=""

for f in *.md; do
    [ -f "$f" ] || continue
    # so newsletters (frontmatter "tipo: newsletter")
    grep -q '^tipo: newsletter$' "$f" 2>/dev/null || continue

    # idade em dias: usa o campo "data:" do frontmatter, senao o prefixo AAAA-MM-DD do nome
    fdate=$(grep -m1 '^data: ' "$f" | sed 's/data: *//;s/"//g' | head -c10)
    if ! [[ "$fdate" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        fdate=$(echo "$f" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2}' || true)
    fi
    [ -n "$fdate" ] || continue

    age_days=$(( ( $(date +%s) - $(date -d "$fdate" +%s) ) / 86400 ))
    [ "$age_days" -ge "$MIN_AGE_DAYS" ] || continue

    ym=$(echo "$fdate" | cut -c1-7)
    dest="$ARCHIVE_BASE/$ym"
    mkdir -p "$dest"
    mv "$f" "$dest/"
    moved=$((moved+1))
    list="$list\n- $f"
done

if [ "$moved" -gt 0 ]; then
    /home/rodrigor/homewatch/vault_sync.sh "arquivo: $moved newsletter(s) movida(s) de dropped/ para arquivo/newsletters/"
    echo -e "Arquivadas $moved newsletter(s):$list"
else
    echo "Nada pra arquivar."
fi
