#!/bin/bash
# anota.sh — cria notas no repo ~/anotacoes seguindo o padrão do acervo e
# mantém o _INDEX.md em dia. É o "vault_sync.sh" das anotações.
#
# Dois gêneros de nota, deliberadamente diferentes:
#   nota    ferramenta/serviço/conceito. Arquivo "<Título>.md" na raiz, frontmatter
#           com anotacao:true (é o que a base Anotacoes.base lista) e ENTRA no _INDEX.md.
#   captura conteúdo capturado (dica, print, newsletter, artigo). Arquivo
#           "AAAA-MM-DD-slug.md", frontmatter title/tipo/fonte/data e NÃO entra no índice.
#
# Uso:
#   anota.sh secoes
#   anota.sh nota "<Título>" "<descrição>" "<tags>" "<url|->" "<relacionados|->" "<seção>" < corpo.md
#   anota.sh captura "<Título>" "<tipo>" "<fonte>" "<tags>" < corpo.md
#   anota.sh index "<Título>" "<seção>" "<descrição>"    (só mexe no índice; idempotente)
#   anota.sh sync "<mensagem de commit>"                  (pull --rebase, commit, push)
#
# tags e relacionados são listas separadas por vírgula. Tag sem "/" vira notes/<tag>.
set -eu
REPO="${ANOTACOES_DIR:-$HOME/anotacoes}"
INDEX="$REPO/_INDEX.md"
[ -d "$REPO/.git" ] || { echo "anota.sh: não achei o clone em $REPO" >&2; exit 1; }

py(){ python3 -c "$1" "${@:2}"; }

case "${1:-}" in
  secoes)
    grep -n '^## ' "$INDEX" | sed 's/^\([0-9]*\):## /\1\t/' ;;

  nota)
    titulo="${2:?uso: anota.sh nota \"Título\" \"descrição\" \"tags\" \"url|-\" \"relacionados|-\" \"seção\"}"
    desc="${3:?descrição}"; tags="${4:?tags}"; url="${5:--}"; rel="${6:--}"; secao="${7:?seção}"
    corpo=$(cat)
    ANOTA_REPO="$REPO" py '
import os, sys, datetime
repo=os.environ["ANOTA_REPO"]
titulo, desc, tags, url, rel, secao, corpo = sys.argv[1:8]
if "/" in titulo: sys.exit("anota.sh: título não pode ter / (vira caminho)")
path=os.path.join(repo, titulo + ".md")
if os.path.exists(path): sys.exit(f"anota.sh: já existe {titulo}.md — edite a nota em vez de recriar")
def norm(t):
    t=t.strip()
    return t if "/" in t else "notes/"+t
tl=[norm(t) for t in tags.split(",") if t.strip()]
rl=[r.strip().strip("[]") for r in rel.split(",") if r.strip() and r.strip()!="-"]
u = url.strip() or "-"
if u == "-": u = "null"
fm =["---", "anotacao: true", f"date: {datetime.date.today().isoformat()}",
     f"descricao: \"{desc.replace(chr(34), chr(39))}\"",
     f"url: {u}", "tags:"]
fm += [f"- {t}" for t in tl]
if rl:
    fm.append("relacionado:")
    fm += [f"- \x27[[{r}]]\x27" for r in rl]
fm.append("---")
open(path,"w").write("\n".join(fm) + "\n" + corpo.strip() + "\n")
print(path)
' "$titulo" "$desc" "$tags" "$url" "$rel" "$secao" "$corpo"
    "$0" index "$titulo" "$secao" "$desc" ;;

  captura)
    titulo="${2:?uso: anota.sh captura \"Título\" \"tipo\" \"fonte\" \"tags\"}"
    tipo="${3:?tipo (dica|artigo|newsletter|...)}"; fonte="${4:?fonte}"; tags="${5:?tags}"
    corpo=$(cat)
    ANOTA_REPO="$REPO" py '
import os, sys, re, unicodedata, datetime
repo=os.environ["ANOTA_REPO"]
titulo, tipo, fonte, tags, corpo = sys.argv[1:6]
hoje=datetime.date.today().isoformat()
s=unicodedata.normalize("NFKD", titulo).encode("ascii","ignore").decode().lower()
slug=re.sub(r"-+","-", re.sub(r"[^a-z0-9]+","-", s)).strip("-")[:70]
path=os.path.join(repo, f"{hoje}-{slug}.md")
if os.path.exists(path): sys.exit(f"anota.sh: já existe {os.path.basename(path)}")
tl=[t.strip().split("/")[-1] for t in tags.split(",") if t.strip()]
fm=["---", f"title: \"{titulo}\"", f"tipo: {tipo}", f"fonte: {fonte}", f"data: {hoje}", "tags:"]
fm+=[f"  - {t}" for t in tl]
fm.append("---")
open(path,"w").write("\n".join(fm) + f"\n\n# {titulo}\n\n" + corpo.strip() + "\n")
print(path)
' "$titulo" "$tipo" "$fonte" "$tags" "$corpo" ;;

  index)
    titulo="${2:?uso: anota.sh index \"Título\" \"seção\" \"descrição\"}"; secao="${3:?seção}"; desc="${4:?descrição}"
    ANOTA_INDEX="$INDEX" py '
import os, sys, datetime
index=os.environ["ANOTA_INDEX"]
titulo, secao, desc = sys.argv[1:4]
linhas=open(index).read().split("\n")
alvo=None
for i,l in enumerate(linhas):
    if l.startswith("## ") and l[3:].strip().lower()==secao.strip().lower(): alvo=i; break
if alvo is None:
    secoes=[l[3:] for l in linhas if l.startswith("## ")]
    sys.exit("anota.sh: seção \x27%s\x27 não existe. Use uma destas:\n  %s" % (secao, "\n  ".join(secoes)))
fim=alvo+1
while fim < len(linhas) and not linhas[fim].startswith("## "): fim+=1
desc=desc.strip()
if not desc.endswith("."): desc+="."
nova=f"- [[{titulo}]] — {desc}"
# já indexada? troca a linha (idempotente: reindexar só atualiza a descrição)
marca=f"- [[{titulo}]] —"
for i,l in enumerate(linhas):
    if l.startswith(marca):
        linhas[i]=nova; open(index,"w").write("\n".join(linhas))
        print(f"índice: descrição de [[{titulo}]] atualizada"); sys.exit(0)
pos=fim
for i in range(alvo+1, fim):
    l=linhas[i]
    if l.startswith("- [["):
        nome=l[4:].split("]]")[0]
        if nome > titulo: pos=i; break
else:
    while pos>alvo+1 and not linhas[pos-1].strip(): pos-=1
linhas.insert(pos, nova)
for i,l in enumerate(linhas):
    if l.startswith("> Atualizado em"):
        linhas[i]=f"> Atualizado em {datetime.date.today().isoformat()}"; break
open(index,"w").write("\n".join(linhas))
print(f"índice: [[{titulo}]] em \x27{secao}\x27 (linha {pos+1})")
' "$titulo" "$secao" "$desc" ;;

  sync)
    msg="${2:?uso: anota.sh sync \"mensagem\"}"
    cd "$REPO"
    # commita ANTES de puxar: com pull --rebase primeiro, editar ou apagar uma
    # nota existente deixava alteracao nao-staged e o rebase se recusava a rodar.
    git add -A
    if git diff --cached --quiet; then
      git rev-list --count origin/main..HEAD 2>/dev/null | grep -qv "^0$" || { echo "anota.sh: nada a commitar"; exit 0; }
    else
      git commit -q -m "$msg"
    fi
    git pull --rebase -q || { echo "anota.sh: pull falhou — resolva à mão em $REPO" >&2; exit 1; }
    git push -q origin main && echo "anota.sh: publicado — $(git log --oneline -1)" ;;

  *) echo "uso: anota.sh secoes|nota|captura|index|sync (veja o cabeçalho do script)" >&2; exit 1 ;;
esac
