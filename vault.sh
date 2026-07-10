#!/bin/bash
# vault.sh — consulta os vaults Obsidian (método PARA) do Rodrigo, espelhados no Pi.
# Repos privados: rodrigor/home -> ~/vault-home ; uana-tech/uana-home -> ~/vault-uana
# (só .md/.excalidraw). Atualizados por git pull (cron 15min) ou "vault.sh update".
# Resultados vêm rotulados por vault: "home/…" ou "uana/…".
#
# Uso:
#   vault.sh index [vault]         mostra o mapa de cada vault (ou de um: home|uana)
#   vault.sh search "termo" [n]    busca literal -> vault/caminho:linha:trecho (n=limite 40)
#   vault.sh find [n] t1 t2 ...    shortlist SEMÂNTICO: notas rankeadas por nº de termos
#                                  distintos que casam (dê sinônimos pt+en). n=limite (padrão 25)
#   vault.sh cat <vault/caminho>   mostra uma nota inteira (ex.: uana/01-projetos/Foo.md)
#   vault.sh ls [vault[/sub]]      lista notas .md
#   vault.sh update                git pull em todos os vaults
set -eu

# Config dos vaults: "label|dir|arquivo-indice"
VAULTS=(
  "home|$HOME/vault-home|INDEX.md"
  "uana|$HOME/vault-uana|uana.tech.md"
)

die(){ echo "vault.sh: $*" >&2; exit 1; }
dir_of(){ local l; for v in "${VAULTS[@]}"; do l="${v%%|*}"; [ "$l" = "$1" ] && { echo "${v#*|}" | cut -d'|' -f1; return; }; done; }
idx_of(){ for v in "${VAULTS[@]}"; do [ "${v%%|*}" = "$1" ] && { echo "${v##*|}"; return; }; done; }
labels(){ for v in "${VAULTS[@]}"; do echo "${v%%|*}"; done; }

cmd="${1:-index}"; shift || true
case "$cmd" in
  index)
    want="${1:-}"
    for l in $(labels); do
      [ -n "$want" ] && [ "$want" != "$l" ] && continue
      d=$(dir_of "$l"); ix=$(idx_of "$l")
      echo "===== [$l] $ix ====="
      if [ -f "$d/$ix" ]; then cat "$d/$ix"; else
        echo "(sem arquivo-índice; notas de topo:)"; find "$d" -maxdepth 2 -name '*.md' -not -path '*/.git/*' 2>/dev/null | sed "s#$d/#$l/#" | sort | head -60
      fi
      echo
    done ;;
  search)
    q="${1:-}"; [ -n "$q" ] || die 'uso: vault.sh search "termo" [limite]'
    n="${2:-40}"; out=""
    for l in $(labels); do
      d=$(dir_of "$l")
      r=$( (cd "$d" && grep -rniI --include='*.md' -e "$q" . 2>/dev/null) | sed "s#^\./#$l/#" || true )
      [ -n "$r" ] && out="${out}${out:+$'\n'}$r"
    done
    if [ -n "$out" ]; then echo "$out" | head -n "$n"; else echo "(sem resultados para: $q)"; fi ;;
  find)
    n=25
    case "${1:-}" in ''|*[!0-9]*) : ;; *) n="$1"; shift ;; esac
    [ "$#" -ge 1 ] || die 'uso: vault.sh find [n] termo1 [termo2 ...]'
    declare -A score
    for l in $(labels); do
      d=$(dir_of "$l")
      for t in "$@"; do
        while IFS= read -r f; do
          f="$l/${f#./}"; score["$f"]=$(( ${score["$f"]:-0} + 1 ))
        done < <(cd "$d" && grep -rilI --include='*.md' -e "$t" . 2>/dev/null)
      done
    done
    if [ "${#score[@]}" -eq 0 ]; then echo "(sem resultados para: $*)"; else
      for f in "${!score[@]}"; do printf '%d\t%s\n' "${score[$f]}" "$f"; done | sort -rn -k1,1 | head -n "$n"
    fi ;;
  cat)
    p="${1:-}"; [ -n "$p" ] || die "uso: vault.sh cat <vault/caminho.md>"
    l="${p%%/}"; l="${p%%/*}"; rel="${p#*/}"
    d=$(dir_of "$l"); [ -n "$d" ] || die "vault desconhecido em '$p' (use: $(labels | tr '\n' ' '))"
    case "$(cd "$d" && realpath -m "$rel")" in
      "$(realpath -m "$d")"/*) : ;;
      *) die "caminho fora do vault" ;;
    esac
    [ -f "$d/$rel" ] || die "nota não encontrada: $p"
    cat "$d/$rel" ;;
  ls)
    arg="${1:-}"; l="${arg%%/*}"; sub="${arg#*/}"; [ "$sub" = "$arg" ] && sub=""
    for lab in $(labels); do
      [ -n "$l" ] && [ "$l" != "$lab" ] && continue
      d=$(dir_of "$lab")
      (cd "$d" && find "./${sub}" -name '*.md' -not -path '*/.git/*' 2>/dev/null) | sed "s#^\./#$lab/#" | sort
    done ;;
  update)
    for l in $(labels); do
      d=$(dir_of "$l")
      if git -C "$d" pull -q --ff-only 2>/dev/null; then echo "[$l] $(git -C "$d" log --oneline -1)"; else echo "[$l] falha no pull"; fi
    done ;;
  *)
    die "comando desconhecido: $cmd (use: index|search|find|cat|ls|update)" ;;
esac
