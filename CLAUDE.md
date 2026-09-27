# Instruções PIrrai

## Comportamento geral
Quando tiver dúvida (sobre intenção, classificação, decisão de design, catalogação, etc.), perguntar ao Rodrigo antes de assumir.

## Repos git — sempre pull antes, push ao concluir
Em qualquer operação num repositório clonado no Pi (homepage, boardgames, eurotrip, anotacoes, etc.), **sempre** `git -C <repo> pull --ff-only` **antes** de editar (o Rodrigo também mexe nesses repos pelo Mac e pode ter avançado o remoto — evita divergência/conflito). Ao concluir a mudança, **enviar (push) direto se o repo for privado** (boardgames, eurotrip, anotacoes — não precisa pedir permissão, é só sincronizar); **na homepage (`rodrigor.github.io`, repo público)** continua valendo a regra de sempre pedir confirmação antes do `git push`, já que publica o site ao vivo. Se o `push` for rejeitado por divergência (alguém empurrou entretanto), não force: puxe de novo e reaplique a mudança por cima do que já está no remoto — nunca sobrescrever o trabalho do Rodrigo.

## Todoist — Agenda
Ao verificar a agenda (todoist.sh today/hoje/list), o comando `today` já move automaticamente as tarefas atrasadas para hoje e exibe quais foram movidas antes da lista. Sempre informe ao usuário quais tarefas foram movidas (se houver).

## Agenda — eventos "dia todo" com emoji
Eventos de dia todo que começam com emoji (🔴🟢🟠 etc.) são Google Meets permanentes dos projetos (Ayty/Portomar/Viva etc.), criados na conta Ayty Business para acesso rápido ao Meet. NÃO são atividades reais. Ignorar ao analisar disponibilidade ou sugerir horários de exercício.

## Agenda — bloqueadores de translado
Eventos "JPA - RT" e "RT - JPA" são bloqueadores de translado de carro entre João Pessoa e Rio Tinto (cidade da Grande João Pessoa). RT = Rio Tinto, não é voo. Rodrigo leciona em Rio Tinto; nesses dias a manhã é ocupada e ele chega em casa ~13:30. Não são atividades reais, apenas travam a agenda.

## Finanças — e-mails de compra
Ao processar ou relatar um e-mail de compra (Amazon, iFood, etc.), sempre substituir o texto bruto do assunto por uma descrição curta e legível do produto/pedido no campo `description` da transação. Ex.: "Travesseiro de viagem ergonômico em U (3 un.)" em vez de "Pedido: ⁦3⁩ Travesseiro Apoio Encosto...".

## Finanças — conta nas transações
Sempre que reportar uma transação financeira (listagem, classificação, resumo, pergunta sobre um lançamento), indicar a conta de origem (Nu Rodrigo, Nu Ayla, Cartão Nu Rodrigo, Cartão Nu Ayla, Conta Global, etc.). Usar formato: <b>[Conta]</b> antes ou junto ao valor/descrição.

## Listas de compras
Antes de adicionar um item à lista de compras (todoist.sh shop), verificar se item similar já existe para evitar duplicata. Normalizar variações (ex: "fermento" = "pó Royal já cadastrado").

## E-mails — endereços a ignorar
Ao buscar e-mails, ignorar mensagens endereçadas a ale@alepessoa.com.br (não são do Rodrigo). A conta Apple do Rodrigo é rodrigoreboucas@mac.com — e-mails da Apple Store/recibos de compra são enviados para esse endereço @mac.com, não para nenhuma das caixas que o PIrrai acessa.

## E-mails — quais caixas o PIrrai acessa
Dois acessos distintos, não confundir:
1. Gmail MCP: rodrigor@dcx.ufpb.br (conta institucional UFPB) — usado para buscas gerais via mcp__claude_ai_Gmail__*.
2. IMAP direto (finance_email.py, config em finance.env): compras@mail.rodrigor.com no servidor mail.supremecluster.com — é para onde os extratos bancários e e-mails de compra são enviados/encaminhados, usado para importar transações financeiras. Há também pirrai@mail.rodrigor.com (email.env) para notificações gerais.
Recibos da Apple Store (@mac.com) não caem em nenhuma dessas — não há encaminhamento configurado até o momento.

## Empresas — nome correto "Phoebus"
O nome da empresa/projeto é <b>Phoebus</b>, não "Fibus". Em transcrições de áudio é comum aparecer como "Fibus" (é assim que soa "Phoebus" falado) — sempre corrigir para "Phoebus" ao interpretar transcrições.

## Projeto Centelha — Telescope (projeto da UANÁ, não pessoal do Rodrigo)
O Centelha é um projeto da <b>UANÁ TECNOLOGIA DA INFORMAÇÃO LTDA</b> (empresa do Rodrigo/Herbert/Lucas/Rony), não uma iniciativa pessoal dele. Produto submetido: <b>Telescope</b> (plataforma de gestão de OKRs, spinoff do laboratório AYTY/UFPB — https://tlscope.io), no Edital FAPESQ nº 022/2026 (Centelha 3 PB).
Rodrigo participa como <b>membro colaborador</b> (sócio investidor + Prof. UFPB) — proponente/coordenador é <b>Herbert Rocha Monteiro</b>.
FONTE DE VERDADE (mais completa que e-mail): nota <code>uana/01-projetos/Centelha/Centelha.md</code> no vault (vault.sh cat uana/01-projetos/Centelha/Centelha.md) — tem cronograma, checklist por fase, enquadramento, pendências. Ver também `uana/01-projetos/Telescope/` para material do produto/pitch.
Página pública de cronograma/resultados: https://materiais.programacentelha.com.br/pb
IMPORTANTE: o cronograma PODE MUDAR — nunca assumir uma data antiga como definitiva; ao ser perguntado sobre prazos/fases/resultados, reconsultar a nota do vault (rodar `vault.sh update` antes se achar que pode estar desatualizada) e/ou a página pública e/ou buscar e-mails recentes de pb@programacentelha.com.br / centelhapb@fapesq.rpp.br.
Cronograma conhecido (pode ter mudado — confirmar antes de informar como certo):
- Fim submissão Fase 1: 25/05/2026 (concluído)
- Resultado preliminar Fase 1: 22/06/2026
- Resultado final Fase 1: 15/07/2026
- Submissão Fase 2: 20/07–10/08/2026
- Resultado preliminar Fase 2: 08/09/2026
- Resultado final Fase 2: 02/10/2026

## Séries — otimização de assinatura de streaming (regra permanente)
Rodrigo quer manter, por streaming, o plano SEM propaganda só enquanto houver ao menos 1 série "ativa" (com episódio novo saindo/recém-saído); se nenhuma série do streaming estiver ativa, ele assina o plano BÁSICO com propaganda. Fonte: series.json (campo tvmaze_id de cada série, checar próximo episódio via TVmaze).
Regra de "ativa": tem episódio que já saiu recentemente ou tem próximo episódio agendado em breve (poucas semanas) — ou seja, temporada em exibição agora. Série "parada" (aguardando renovação/nova temporada sem data próxima) NÃO conta como ativa.
Sempre que o status de alguma série mudar (temporada atual termina = fica parada; ou nova temporada é anunciada/estreia = fica ativa), reavaliar o agrupamento por streaming e avisar o Rodrigo se a recomendação mudar (downgrade pra básico c/ propaganda ou upgrade pra sem propaganda). Já existem lembretes criados (reminder_add.sh) para os retornos previstos de Marshals (Paramount+, 04/10/2026) e O Senhor dos Anéis: Os Anéis do Poder (Prime Video, 11/11/2026) — avisar antes da estreia pra ele voltar a tempo pro plano sem propaganda. Landman T3 (Paramount+) confirmada oficialmente para 16/11/2026 (pôster oficial, checado em 2026-09-18) — como o retorno de Marshals em 04/10 já cobre a necessidade de estar sem propaganda a partir dessa data, e Landman está dentro dessa mesma janela contínua no Paramount+, não precisa de lembrete extra — só mantiver o plano sem propaganda ativo entre 04/10 e pelo menos 16/11.

## Finanças — Outback sempre nível N3
Toda transação do <b>Outback</b> (restaurante) é categoria <b>Refeições</b> mas nível <b>N3 (Discricionário)</b> — diferente do padrão da categoria (N2). Como o motor de regras (finance_rules.py) ainda não aplica nível automaticamente por regra (só categoria — ver item no backlog.sh), aplicar manualmente via SQL (`UPDATE transactions SET nivel=3 WHERE id=...`) toda vez que aparecer um lançamento do Outback.

## Finanças — Anthropic sempre categoria "IA", nível N3
Toda transação com "Anthropic" na descrição (assinatura Claude, IOF de volta, etc.) é categoria <b>IA</b>, nível <b>N3 (Discricionário)</b>. Já existe regra cadastrada (`finance.sh rule add description "Anthropic" "IA"`) que aplica a categoria sozinha, mas o nível ainda precisa ser setado manualmente via SQL (`UPDATE transactions SET nivel=3 WHERE description LIKE '%Anthropic%' AND nivel IS NOT 3`) toda vez que aparecer lançamento novo — mesma limitação do Outback (motor de regras não aplica nível ainda).

## Vault — anexos do Plaud
Anexos/arquivos relacionados ao Plaud (app de gravação com IA — plaud.ai) devem ser salvos em `inbox/dropped/plaud/` no vault-home (pasta já criada). Essa é a pasta padrão pra esse tipo de conteúdo; `inbox/dropped/` (e subpastas) já tem exceção no `.gitignore` liberando qualquer tipo de arquivo, então PDFs/anexos exportados do Plaud vão pro git normalmente.

## Newsletters/conteúdo — ferramentas e links interessantes viram tarefa no Todoist
Sempre que uma newsletter (ou outro conteúdo processado, ex.: e-mail, print) mencionar uma ferramenta/produto ou um link que valha a pena o Rodrigo conferir depois, criar uma tarefa no Todoist no projeto **Ferramentas**: `todoist.sh add "<nome da ferramenta>" "" "Ferramentas" "" "<resumo curto do que é + link>"`.
- O link colocado na descrição precisa ser a URL REAL do produto (ex.: buscar `nome-da-ferramenta site oficial` via WebSearch), NUNCA o link de rastreamento/redirecionamento do próprio e-mail (newsletters como Evolving AI Insights/AI Secret usam beehiiv e o `href` é um redirect tipo `elinkc04.newsletter...`, não a URL do produto — não usar esse link).
- Não duplicar: se a ferramenta já tem tarefa aberta no projeto Ferramentas, não recriar.
- Isso vale tanto para os itens da seção "Trending AI Tools"/"Quick Hits" das newsletters quanto para qualquer ferramenta citada no corpo de uma matéria.

## Anotações — "anota isso" vai para o repo `anotacoes`
O acervo de anotações (~280 notas Obsidian) fica em `~/anotacoes` (repo privado `rodrigor/anotacoes`, label `anotacoes` no `repos.sh`). Sempre que o Rodrigo mandar anotar/guardar algo, **crie a nota lá e atualize o `_INDEX.md`** — usando `/home/rodrigor/homewatch/anota.sh`, nunca escrevendo o `.md` ou o índice à mão.
- **Antes**, `git -C ~/anotacoes pull --ff-only` e procure nota existente do assunto (`repos.sh find`): se existir, **edite** em vez de duplicar.
- `anota.sh nota "Título" "descrição de uma linha" "tags" "url|-" "relacionadas|-" "Seção" <<< "corpo"` — ferramenta/serviço/conceito, entra no índice. `anota.sh secoes` lista as seções válidas.
- `anota.sh captura "Título" "tipo" "fonte" "tags" <<< "corpo"` — conteúdo datado (dica, print, newsletter): vira `AAAA-MM-DD-slug.md` e **não** entra no índice.
- `anota.sh artigo "AAAA-primeiroautor-slug" "<pdf|->" "descrição" <<< "nota completa"` — **artigo científico** (paper, preprint, relatório técnico; em geral o PDF que o Rodrigo manda). Antes, leia `~/anotacoes/CLAUDE.md`, `Artigos/_template-artigo.md` e `Artigos/_taxonomia-pesquisa.md` e escreva a nota inteira no template. O script grava em `Artigos/`, copia o PDF para `Artigos/pdf/`, recusa termo fora da taxonomia e indexa na seção Artigos. Post de blog continua sendo captura.
- `anota.sh sync "mensagem"` publica (repo privado — push é só sincronizar com o Obsidian do Mac).

## Boardgames — a coleção mora aqui no Pi

Desde 2026-09-03 a coleção do Rodrigo **mora só no Pi**, em `~/boardgames` (repo privado
`rodrigor/boardgames`, label `boardgames` no `repos.sh`). Não existe mais cópia no Mac — se
ele perguntar qualquer coisa sobre jogos, partidas, tags ou duração, a resposta vem **daqui**.

**Consulta é SQL contra `~/boardgames/colecao.db`.** Nunca leia o `colecao.md` para extrair
dado: ele é uma nota gerada, sempre atrás do banco. O `~/boardgames/CLAUDE.md` documenta
schema, views e as armadilhas do export — leia antes de montar consulta não trivial.

```bash
sqlite3 -box ~/boardgames/colecao.db "SELECT nome, partidas FROM v_analise ORDER BY partidas DESC LIMIT 10"
```

Views: `v_colecao` (inventário: o que ele tem), `v_analise` (**universo padrão para analisar
uso** — médios e pesados, sem filler nem party, porque partida de filler quase nunca é
registrada e o agregado viraria viés), `v_partidas`, `v_placar`, `v_duracao` (use `mediana_min`,
**nunca média** — uma partida com cronômetro esquecido desloca a média em horas), `v_jogadores`
(com quantos é *bom*, não só permitido), `v_tags`, `v_categorias`, `v_mecanicas`, `v_ranking`
(coluna é `rank_geral`, mais os subdomínios).

### NUNCA escreva no colecao.db

O banco é **artefato**: toda ingestão o recria do zero. Um `UPDATE` nele parece funcionar e
some sem aviso na próxima geração. Toda alteração vai na **fonte**:

| O Rodrigo pede | Você edita |
|---|---|
| tag de jogo (card game, filler, duelo, euro:pesado…) | `~/boardgames/classificacao.tsv` |
| corrigir duração/validade de uma partida | `~/boardgames/correcoes.tsv` |
| registrar venda (comprador, valor, pagamento) | `~/boardgames/vendas.md` |
| empréstimo de jogo | `~/homewatch/emprestimos.sh` |
| inventário, nota, partida nova | **não dá** — é no BGStats do iPhone dele |

Depois de mexer em TSV, **regenere e sincronize**:

```bash
cd ~/boardgames && git pull --ff-only && python3 gerar-colecao.py && git add -A && git commit -m "..." && git push
```

O `gerar-colecao.py` reingere e reescreve `colecao.md`; `--so-md` só re-renderiza a nota (não
serve quando a mudança é de dado). Commite `colecao.db` **e** `colecao.md` junto com a fonte que
mudou — os artefatos andam no mesmo commit. Commits em português, no imperativo.

### Export novo do BGStats chega por aqui

O BGStats só exporta para o iCloud do iPhone, e o Pi não lê iCloud. O caminho é ele **mandar o
JSON como anexo neste chat**. Quando chegar um `BGStatsExport*.json` no `agentwork`:

```bash
mv ~/homewatch/agentwork/upload_*_BGStats*.json ~/boardgames/entrada/
cd ~/boardgames && BGSTATS_DIR=~/boardgames/entrada python3 gerar-colecao.py
```

`entrada/` é a pasta de troca do Pi (gitignorada) — **é ela** que vale como `BGSTATS_DIR` aqui,
nunca o `agentwork`, senão qualquer JSON que ele mandar pelo Telegram viraria candidato a export.
O script arquiva o JSON em `exports/`, recria o banco e regenera a nota. Ele **recusa export mais
antigo** que o último arquivado (a ingestão apaga e recria: um backup velho apagaria meses de
partidas) — se recusar, não force sem falar com ele.

Depois de ingerir, confira que não houve perda antes de commitar: o número de partidas nunca
deve cair. `sqlite3 ~/boardgames/colecao.db "SELECT COUNT(*) FROM partidas"` — hoje são 1801.

### Enriquecimento do BGG

`enriquecer-bgg.py` busca categoria/mecânica/peso na XML API2 (o BGStats não exporta isso). Exige
o `~/boardgames/.bgg-token` (já está no Pi, gitignorado — **nunca commite**). O cache em
`bgg/cache/` evita rebater na API; rodar de novo só busca jogo novo. Depois dele, rode
`gerar-colecao.py` **sem** `--so-md`, senão o enriquecimento não chega ao banco.

### Devolver as tags ao BGStats — pendência conhecida

`exportar-bgstats.py` gera um JSON para o app reimportar, mas **este bot não envia arquivo**
(não há `sendDocument` no `telegram_agent.sh`). Então o arquivo fica preso no Pi. Se ele pedir,
avise disso e ofereça servir por `tailscale serve` para ele salvar pelo Safari do iPhone. Nunca
diga que mandou o arquivo.

### Venda de jogo — site público x controle privado
Quando o Rodrigo avisar que vendeu um jogo do lote à venda (rodrigor.com/boardgames/vendas/AAAA-MM/): no **site público** (repo `homepage`) só mude o `data-status`/badge da linha pra `vendido` — **nunca** escreva nome de comprador, valor recebido ou forma de pagamento nesse repo, é público. Peça confirmação antes do `git push` (regra normal da homepage). Os dados do comprador (nome, valor pedido/recebido, forma de pagamento) vão **só** no controle privado `vendas.md` do repo `boardgames` (label `boardgames` no `repos.sh`) — crie/edite essa linha lá e sincronize (repo privado, pode dar push direto). Se o valor recebido não foi informado/confirmado (sem comprovante), registre como "a confirmar" em vez de assumir o preço da tabela, e só lance a receita em `finance.sh` depois de confirmado.

## Servidor lab.ayty.org — laboratório de disciplinas da UFPB
`lab.ayty.org` (85.239.231.100) é o servidor de **laboratório** que o Rodrigo usa nas suas duas
disciplinas na universidade: <b>Gerência de Redes</b> e <b>Projeto Avançado 1</b>. Ele traz problemas
desse servidor pra resolver por aqui — tratar como contexto de sala de aula/laboratório dessas
duas disciplinas, não como infra pessoal/produção. Diagnóstico feito em 2026-09-07: SSH (porta 22)
respondendo normal (`OpenSSH_9.6p1` em Ubuntu), HTTP (porta 80) responde com redirect 308 pra
HTTPS, mas a porta 443 quebra o handshake TLS (`TLSv1.3 alert: internal error`) antes de trocar
certificado — falha do lado do serviço web/proxy do servidor, não da rede/DNS.
