#!/bin/bash
# vault.sh — consulta o vault Obsidian "home" (método PARA) do Rodrigo.
# Espelho local em ~/vault-home (repo privado github.com/rodrigor/home; só .md/.excalidraw).
# Atualizado por git pull (cron a cada 15min) ou sob demanda com "vault.sh update".
#
# Uso:
#   vault.sh index                 mostra o INDEX.md (mapa do vault — comece por aqui)
#   vault.sh search "termo" [n]    busca nas notas -> caminho:linha:trecho (n=limite, padrão 40)
#   vault.sh cat <caminho.md>      mostra uma nota inteira (caminho relativo ao vault)
#   vault.sh ls [subpasta]         lista notas .md de uma pasta
#   vault.sh update                git pull (traz o mais recente do GitHub)
set -eu
VAULT="${VAULT_DIR:-$HOME/vault-home}"

die(){ echo "vault.sh: $*" >&2; exit 1; }
[ -d "$VAULT" ] || die "vault não encontrado em $VAULT (clone: gh repo clone rodrigor/home $VAULT)"

cmd="${1:-index}"; shift || true
case "$cmd" in
  index)
    cat "$VAULT/INDEX.md" ;;
  search)
    q="${1:-}"; [ -n "$q" ] || die 'uso: vault.sh search "termo" [limite]'
    n="${2:-40}"
    cd "$VAULT"
    res=$(grep -rniI --include='*.md' -e "$q" . 2>/dev/null | sed 's|^\./||' | head -n "$n" || true)
    if [ -n "$res" ]; then echo "$res"; else echo "(sem resultados para: $q)"; fi ;;
  cat)
    rel="${1:-}"; [ -n "$rel" ] || die "uso: vault.sh cat <caminho.md>"
    f="$VAULT/$rel"
    case "$(cd "$VAULT" && realpath -m "$rel")" in
      "$(realpath -m "$VAULT")"/*) : ;;   # dentro do vault
      *) die "caminho fora do vault" ;;
    esac
    [ -f "$f" ] || die "nota não encontrada: $rel"
    cat "$f" ;;
  ls)
    sub="${1:-}"
    cd "$VAULT"
    find "./${sub}" -name '*.md' -not -path '*/.git/*' 2>/dev/null | sed 's|^\./||' | sort ;;
  update)
    git -C "$VAULT" pull -q --ff-only && echo "vault atualizado ($(git -C "$VAULT" log --oneline -1))" ;;
  *)
    die "comando desconhecido: $cmd (use: index|search|cat|ls|update)" ;;
esac
