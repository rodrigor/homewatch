#!/bin/bash
# vault_publish.sh — salva um arquivo (PDF/binário) no vault e sincroniza com o GitHub.
# O .gitignore do vault é allowlist (só *.md/*.excalidraw); aqui usamos `git add -f`
# pra versionar SÓ o arquivo escolhido, filado no diretório certo, sem arrastar o resto.
#
# Uso: vault_publish.sh <arquivo_origem> <destino_no_vault> ["mensagem de commit"]
#   <destino_no_vault>: caminho relativo à raiz do vault. Se terminar em '/', mantém o
#   nome original do arquivo. Ex.: "projetos/ayty.portomar 2025/contratos/"
set -uo pipefail
VAULT="/home/rodrigor/vault-home"
SRC="${1:?uso: vault_publish.sh <origem> <destino_no_vault> [msg]}"
DEST="${2:?uso: vault_publish.sh <origem> <destino_no_vault> [msg]}"
MSG="${3:-}"

[ -f "$SRC" ] || { echo "ERRO: origem não encontrada: $SRC"; exit 1; }

# resolve destino (dir/ mantém nome de origem)
case "$DEST" in */) TARGET="$VAULT/$DEST$(basename "$SRC")";; *) TARGET="$VAULT/$DEST";; esac
REL="${TARGET#$VAULT/}"

# aviso de tamanho (git não é bom p/ binário grande)
SZ=$(stat -c%s "$SRC"); MB=$((SZ/1024/1024))
[ "$MB" -ge 25 ] && echo "⚠️  arquivo grande (${MB}MB) — fica no histórico do git para sempre."

mkdir -p "$(dirname "$TARGET")"
cp -f "$SRC" "$TARGET"

cd "$VAULT" || exit 1
git pull -q --ff-only origin main 2>/dev/null   # sincroniza antes de empurrar (evita non-ff)
git add -f "$REL"
if git diff --cached --quiet; then
  echo "nada a commitar (arquivo idêntico já versionado): $REL"; exit 0
fi
git commit -q -m "${MSG:-anexo: $REL}"
if git push -q origin main 2>/dev/null; then
  echo "✅ publicado e sincronizado: $REL"
  echo "   (aparece no seu computador no próximo pull do Obsidian Git)"
else
  echo "⚠️  commit feito, mas push falhou (rede/conflito). Rode: cd $VAULT && git pull --rebase && git push"
fi
