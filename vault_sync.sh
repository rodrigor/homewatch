#!/bin/bash
# vault_sync.sh ["<mensagem de commit>"]
# Commit + push do vault ~/vault-home (repo github.com/rodrigor/home).
# O .gitignore do vault é allowlist (só *.md/*.excalidraw entram), então add -A é seguro.
set -uo pipefail
VAULT="/home/rodrigor/vault-home"
MSG="${1:-vault: atualização automática (PIrrai)}"
cd "$VAULT" || { echo "vault não encontrado em $VAULT"; exit 1; }
git add -A
if git diff --cached --quiet; then echo "nada a commitar"; exit 0; fi
git commit -q -m "$MSG" || { echo "commit falhou"; exit 2; }
if git push -q 2>/tmp/vault_push.err; then
  echo "ok: commit+push — $MSG"
else
  echo "commit feito, push FALHOU: $(tail -1 /tmp/vault_push.err)"; exit 3
fi
