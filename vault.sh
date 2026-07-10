#!/bin/bash
# vault.sh — consulta o vault Obsidian "home" (método PARA) do Rodrigo.
# Espelho local em ~/vault-home (repo privado github.com/rodrigor/home; só .md/.excalidraw).
# Atualizado por git pull (cron a cada 15min) ou sob demanda com "vault.sh update".
#
# Uso:
#   vault.sh index                 mostra o INDEX.md (mapa do vault — comece por aqui)
#   vault.sh search "termo" [n]    busca literal -> caminho:linha:trecho (n=limite, padrão 40)
#   vault.sh find [n] t1 t2 ...    shortlist SEMÂNTICO: notas rankeadas por nº de termos
#                                  distintos que casam (dê sinônimos pt+en). n=limite (padrão 25)
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
  find)
    n=25
    case "${1:-}" in ''|*[!0-9]*) : ;; *) n="$1"; shift ;; esac  # 1º arg só-dígitos = limite
    [ "$#" -ge 1 ] || die 'uso: vault.sh find [n] termo1 [termo2 ...]'
    cd "$VAULT"
    declare -A score
    for t in "$@"; do
      while IFS= read -r f; do
        f="${f#./}"; score["$f"]=$(( ${score["$f"]:-0} + 1 ))
      done < <(grep -rilI --include='*.md' -e "$t" . 2>/dev/null)
    done
    if [ "${#score[@]}" -eq 0 ]; then echo "(sem resultados para: $*)"; else
      for f in "${!score[@]}"; do printf '%d\t%s\n' "${score[$f]}" "$f"; done \
        | sort -rn -k1,1 | head -n "$n"
    fi ;;
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
    die "comando desconhecido: $cmd (use: index|search|find|cat|ls|update)" ;;
esac
