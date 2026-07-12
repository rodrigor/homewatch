# Instruções PIrrai

## Comportamento geral
Quando tiver dúvida (sobre intenção, classificação, decisão de design, catalogação, etc.), perguntar ao Rodrigo antes de assumir.

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
Sempre que o status de alguma série mudar (temporada atual termina = fica parada; ou nova temporada é anunciada/estreia = fica ativa), reavaliar o agrupamento por streaming e avisar o Rodrigo se a recomendação mudar (downgrade pra básico c/ propaganda ou upgrade pra sem propaganda). Já existem lembretes criados (reminder_add.sh) para os retornos previstos de Marshals (Paramount+, 04/10/2026) e O Senhor dos Anéis: Os Anéis do Poder (Prime Video, 11/11/2026) — avisar antes da estreia pra ele voltar a tempo pro plano sem propaganda.
