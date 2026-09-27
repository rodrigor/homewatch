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
#   anota.sh artigo "<AAAA-autor-slug>" "<pdf|->" "<descrição>" < nota.md   (Artigos/, valida taxonomia)
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

  artigo)
    # Artigo científico: nota completa (frontmatter + corpo, seguindo
    # Artigos/_template-artigo.md) vem pelo stdin. O script valida contra a
    # taxonomia, copia o PDF para Artigos/pdf/ e indexa na seção Artigos.
    nome="${2:?uso: anota.sh artigo \"AAAA-primeiroautor-slug\" \"pdf|-\" \"descrição do índice\" < nota.md}"
    pdf="${3:?caminho do PDF ou -}"; desc="${4:?descrição do índice}"
    corpo=$(cat)
    ANOTA_REPO="$REPO" py '
import os, sys, re, shutil, yaml
repo=os.environ["ANOTA_REPO"]
nome, pdf, corpo = sys.argv[1:4]
art=os.path.join(repo, "Artigos")
erros=[]
if not re.fullmatch(r"\d{4}-[a-z0-9]+(-[a-z0-9]+)+", nome):
    sys.exit("anota.sh: nome deve ser AAAA-primeiroautor-slug, minúsculo e sem acento (ex.: 2026-furgale-nvidia-oo-agents)")
path=os.path.join(art, nome + ".md")
if os.path.exists(path): sys.exit(f"anota.sh: já existe Artigos/{nome}.md — edite a nota em vez de recriar")
m=re.match(r"\s*---\n(.*?)\n---\n(.*)", corpo, re.S)
if not m: sys.exit("anota.sh: a nota precisa começar com o frontmatter (--- ... ---) do _template-artigo.md")
try: fm=yaml.safe_load(m.group(1)) or {}
except Exception as e: sys.exit(f"anota.sh: frontmatter inválido: {e}")
corpo_md=m.group(2)

# vocabulário controlado, lido da própria taxonomia
taxp=os.path.join(art, "_taxonomia-pesquisa.md")
if not os.path.exists(taxp): sys.exit("anota.sh: não achei Artigos/_taxonomia-pesquisa.md — rode git -C " + repo + " pull --ff-only")
tax=open(taxp).read()
def termos(secao):
    b=re.search(r"^## `%s`.*?(?=^## |\Z)" % secao, tax, re.S|re.M)
    return set(re.findall(r"^\| `([a-z0-9-]+)` \|", b.group(0), re.M)) if b else set()
voc={k: termos(k) for k in ("abordagem","metodologia","metodos")}
ctx=re.search(r"^\| `contexto` \|(.*)$", tax, re.M)
voc["contexto"]=set(re.findall(r"`([a-z]+)`", ctx.group(1))) if ctx else set()

def lista(v): return [] if v in (None,"") else (v if isinstance(v,list) else [v])
if fm.get("category")!="artigo": erros.append("category deve ser artigo")
for k in ("citekey","title","autores","ano","descricao"):
    if not fm.get(k): erros.append(f"{k} vazio")
if not lista(fm.get("metodologia")): erros.append("metodologia vazia (use ao menos um termo)")
for k in ("abordagem","metodologia","metodos","contexto"):
    for t in lista(fm.get(k)):
        if str(t) not in voc[k]:
            erros.append(f"{k}: \x27{t}\x27 não está em _taxonomia-pesquisa.md (acrescente lá, com definição, antes de usar)")
if fm.get("status") not in ("a ler","lendo","lido"): erros.append("status deve ser: a ler | lendo | lido")
if "notes/artigo" not in lista(fm.get("tags")): erros.append("tags precisa conter notes/artigo")
if not re.search(r"^## Método", corpo_md, re.M): erros.append("falta a seção ## Método")
if not re.search(r"^## Onde isso me toca", corpo_md, re.M): erros.append("falta a seção ## Onde isso me toca")
if pdf!="-":
    if not os.path.isfile(pdf): erros.append(f"PDF não encontrado: {pdf}")
    elif open(pdf,"rb").read(5)!=b"%PDF-": erros.append(f"{pdf} não é PDF")
if erros: sys.exit("anota.sh: nota recusada:\n  - " + "\n  - ".join(erros))

fmtxt=m.group(1)
if pdf!="-":
    os.makedirs(os.path.join(art,"pdf"), exist_ok=True)
    shutil.copyfile(pdf, os.path.join(art, "pdf", nome + ".pdf"))
    alvo=f"pdf: \"[[{nome}.pdf]]\""
    fmtxt=re.sub(r"^pdf:.*$", alvo, fmtxt, flags=re.M) if re.search(r"^pdf:", fmtxt, re.M) else fmtxt + "\n" + alvo
open(path,"w").write("---\n" + fmtxt.strip("\n") + "\n---\n" + corpo_md.lstrip("\n").rstrip() + "\n")
print(path)
' "$nome" "$pdf" "$corpo"
    "$0" index "$nome" "Artigos" "$desc" ;;

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

  *) echo "uso: anota.sh secoes|nota|captura|artigo|index|sync (veja o cabeçalho do script)" >&2; exit 1 ;;
esac
