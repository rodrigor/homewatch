#!/bin/bash
# repos.sh — consulta os repositórios temáticos do Rodrigo, clonados no Pi.
#
# Desde 2026-08-23 o vault ~/vault-home NÃO é mais sincronizado no git: cada
# assunto virou um repositório próprio no GitHub. Este script é o vault.sh
# desses repos — mesma interface, mesma ideia (ler é barato, chutar é caro).
#
# O Rodrigo trabalha neles no Mac e faz push; o clone do Pi pode estar velho.
# Rode "repos.sh update <label>" antes de responder algo que dependa do estado atual.
#
# Uso:
#   repos.sh list                  catálogo: o que é cada repo e a regra que pega
#   repos.sh ls [label[/sub]]      lista os arquivos de texto do repo
#   repos.sh cat <label/caminho>   mostra um arquivo inteiro (ex.: eurotrip/roteiro.md)
#   repos.sh search "termo" [n]    busca literal -> label/caminho:linha:trecho (n=limite 40)
#   repos.sh find [n] t1 t2 ...    shortlist SEMÂNTICO: arquivos rankeados por nº de
#                                  termos distintos que casam (dê sinônimos pt+en)
#   repos.sh update [label]        git pull (todos, ou um)
set -eu

# "label|dir|descrição (a regra que pega vem depois de — )"
REPOS=(
  "eurotrip|$HOME/2026.eurotrip|Viagem à Alemanha e Itália, out/nov 2026, 4 pessoas (Rodrigo, Ayla, Ana, Gabriela). Roteiro, reservas, orçamento, documentos. — programacao.md é a fonte de verdade da linha do tempo; README.md e programacao.html são GERADOS (build_readme.py / build_programacao.py), não edite à mão. NUNCA comprar, reservar, pagar ou submeter formulário de visto."
  "homepage|$HOME/rodrigor.github.io|Site pessoal do Rodrigo (rodrigor.com): Jekyll + Bootstrap 5 no GitHub Pages. Páginas em pt na raiz (index.md, cv.md, contact.md) e em inglês sob en/; _data/i18n.yml tem os textos de interface e _data/links.yml os perfis acadêmicos. — ÚNICO repo de ESCRITA: mudanças na página são feitas aqui, editando o .md/.yml da página certa nos DOIS idiomas quando o texto aparece nos dois. Todo push na main PUBLICA o site ao vivo (.github/workflows/deploy.yml) — commit local sempre, push só quando o Rodrigo mandar publicar. Não mexer em _sass/bootstrap/ (vendor) nem em _site/ (build)."
  "boardgames|$HOME/boardgames|Coleção de jogos de tabuleiro: inventário e histórico de partidas. — colecao.md é GERADO do export do app BGStats pelo gerar-colecao.py; NUNCA edite à mão nem 'corrija' um dado nele. A fonte de verdade é o BGStats/BGG (usuário rodrigor); conserto é lá + novo export."
)

die(){ echo "repos.sh: $*" >&2; exit 1; }
labels(){ for r in "${REPOS[@]}"; do echo "${r%%|*}"; done; }
# devolvem string vazia (e status 0) quando o label não existe — quem chama valida.
# Sem o "return 0" final, o for termina com status 1 e o set -e mata o script
# antes de a mensagem de erro sair.
dir_of(){ for r in "${REPOS[@]}"; do [ "${r%%|*}" = "$1" ] && { local t="${r#*|}"; echo "${t%%|*}"; return 0; }; done; return 0; }
desc_of(){ for r in "${REPOS[@]}"; do [ "${r%%|*}" = "$1" ] && { echo "${r##*|}"; return 0; }; done; return 0; }

# arquivos de texto do repo (ignora .git e os binários grandes: PDFs, imagens, exports)
files_of(){ find "$1" -path '*/.git' -prune -o -type f \
    \( -name '*.md' -o -name '*.py' -o -name '*.txt' -o -name '*.html' -o -name '*.yml' \) -print 2>/dev/null; }

cmd="${1:-list}"; shift || true
case "$cmd" in
  list)
    for l in $(labels); do
      d=$(dir_of "$l")
      if [ -d "$d" ]; then
        n=$(files_of "$d" | wc -l)
        printf '===== [%s] %s (%s arquivos de texto) =====\n%s\n\n' "$l" "$d" "$n" "$(desc_of "$l")"
      else
        printf '===== [%s] AUSENTE (%s não existe) =====\n\n' "$l" "$d"
      fi
    done ;;
  ls)
    want="${1:-}"; sub=""
    case "$want" in */*) sub="${want#*/}"; want="${want%%/*}";; esac
    for l in $(labels); do
      [ -n "$want" ] && [ "$want" != "$l" ] && continue
      d=$(dir_of "$l"); [ -d "$d" ] || continue
      files_of "$d" | sed "s#^$d/#$l/#" | { [ -n "$sub" ] && grep "^$l/$sub" || cat; } | sort
    done ;;
  cat)
    spec="${1:-}"; [ -n "$spec" ] || die "uso: repos.sh cat <label/caminho>"
    l="${spec%%/*}"; rel="${spec#*/}"
    d=$(dir_of "$l"); [ -n "$d" ] || die "repo desconhecido: $l (veja repos.sh list)"
    f="$d/$rel"
    # não sai do repo
    case "$(realpath -m "$f")" in "$(realpath -m "$d")"/*) :;; *) die "caminho fora do repo: $spec";; esac
    [ -f "$f" ] || die "não encontrado: $spec"
    cat "$f" ;;
  search)
    termo="${1:-}"; [ -n "$termo" ] || die "uso: repos.sh search \"termo\" [n]"
    n="${2:-40}"
    for l in $(labels); do
      d=$(dir_of "$l"); [ -d "$d" ] || continue
      files_of "$d" | while read -r f; do
        grep -Hin -- "$termo" "$f" 2>/dev/null | sed "s#^$d/#$l/#"
      done
    done | head -n "$n" ;;
  find)
    n=25; case "${1:-}" in ''|*[!0-9]*) :;; *) n="$1"; shift;; esac
    [ $# -gt 0 ] || die "uso: repos.sh find [n] termo1 termo2 ..."
    for l in $(labels); do
      d=$(dir_of "$l"); [ -d "$d" ] || continue
      files_of "$d" | while read -r f; do
        score=0
        for t in "$@"; do grep -qi -- "$t" "$f" 2>/dev/null && score=$((score+1)); done
        # if/fi, não "[ ] && cmd": com score 0 o teste falha, vira o último status do
        # corpo do while e o set -e mata o subshell — engolindo o resto dos repos.
        if [ "$score" -gt 0 ]; then
          printf '%s\t%s\n' "$score" "$(echo "$f" | sed "s#^$d/#$l/#")"
        fi
      done
    done | sort -rn | head -n "$n" ;;
  update)
    want="${1:-}"
    for l in $(labels); do
      [ -n "$want" ] && [ "$want" != "$l" ] && continue
      d=$(dir_of "$l")
      [ -d "$d/.git" ] || { echo "$l: sem clone em $d"; continue; }
      out=$(git -C "$d" pull --ff-only -q 2>&1) && echo "$l: ok" || echo "$l: pull falhou — $out"
    done ;;
  *) die "comando desconhecido: $cmd (list|ls|cat|search|find|update)";;
esac
