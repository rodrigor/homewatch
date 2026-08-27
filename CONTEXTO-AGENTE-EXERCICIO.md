# Contexto — Agente de Exercício Físico (PIrrai)

Documento de handoff escrito em 2026-08-27 para trabalhar, em outra sessão, na
**melhoria do agente de hábito de exercício**. Descreve o harness inteiro (como o
PIrrai roda no Pi), o subsistema de hábitos, o estado atual dos dados e os
problemas conhecidos. Tudo verificado no host, não de memória.

---

## 1. O harness: o que é o PIrrai

**Host:** Raspberry Pi (`pi`, Debian 13, ARM64), usuário `rodrigor`, repo em
`/home/rodrigor/homewatch`. Tudo é bash + jq + python3 solto no diretório — sem
framework, sem container. O estado mutável fica em `state/` (arquivos-flag e logs)
e os dados de domínio em JSON/SQLite no próprio repo.

**O agente principal** é `telegram_agent.sh` (~53 KB, um único script), rodando
como `homewatch-agent.service` (systemd, `Restart=always`, User=rodrigor).
Há um `homewatch-watchdog.service` que vigia `state/heartbeat` e reinicia se o
loop travar, e um `service-health.timer` que alerta no Telegram sobre timers
atrasados e login do Claude expirado.

### 1.1 O loop

```
while true:
  process_print_queue      # fila de impressão
  check_new_devices        # MAC novo na rede -> alerta
  process_reminders        # reminders.json (hora ou chegada em casa)
  process_screen_nudges    # uso de tela das filhas
  process_habits           # <<< o coach de hábitos
  echo now > state/heartbeat
  getUpdates (long polling, timeout 50s)  ->  trata cada update
```

Ou seja: **as rotinas proativas rodam no mesmo loop do long polling**, uma vez a
cada ciclo (≈ a cada 50s ou a cada mensagem), cada uma com seu próprio
antirrepetição por arquivo em `state/` ou por campo no JSON do domínio.

### 1.2 Como o Claude é chamado (caminho admin)

O texto da mensagem vira uma chamada única do CLI:

```bash
REPLY=$(cd "$WORKDIR" && timeout ${CLAUDE_TIMEOUT:-180} \
  claude -p $CONT --model "$USEMODEL" --dangerously-skip-permissions \
  --system-prompt "$SYS" "$text")
```

- `WORKDIR=homewatch/agentwork` — cwd isolado (não colide com a sessão
  interativa do Rodrigo em `/home/rodrigor`). É onde caem os uploads do Telegram.
- `$CONT` = `--continue` se existir o flag `state/agent_session_active`.
  `/reset` apaga o flag = conversa nova.
- `$SYS` é **um heredoc gigante dentro do próprio script** (`telegram_agent.sh`,
  ~linhas 599-658): todo o "manual de operação" do PIrrai — Pi-hole, inventário
  de dispositivos, recados para as filhas, lembretes, **hábitos**, Todoist,
  agenda, finanças, vault da Uaná, repos temáticos, homepage, anotações, digest,
  YouTube, impressão, formato HTML do Telegram, protocolo de tarefas
  multi-etapas. Não há arquivo de prompt separado: **editar o prompt = editar o
  script e reiniciar o serviço** (`sudo systemctl restart homewatch-agent`).
- Modelo: `state/agent_model` (`/opus`, `/sonnet`, `/haiku`), com override por
  mensagem via prefixo `opus: ...`.
- Recuperação: se a resposta vier vazia, retry sem `--continue`; se vier erro de
  auth (o CLI imprime 401 no **stdout** e sai 0), `claude_auth.sh` detecta,
  grava marcador para o `service_health.sh` e devolve mensagem legível.

### 1.3 Papéis (multi-usuário)

O `chat_id` define o papel: **admin** (Rodrigo, tudo liberado), **finance**
(Ayla — só `finance_handler.sh`), **kid** (Gabi/Ana — `kid_handler.sh`, persona
própria, cotas, sandbox). Qualquer outro remetente é ignorado.

**Detalhe crítico para o agente de hábitos:** as chamadas de LLM das personas
(filhas) rodam como usuário separado `pirraikid` (`sudo -H -u pirraikid claude`)
— e `habit_coach.sh` e `habit_analyze.sh` **também usam `pirraikid`**, mesmo
quando o hábito é do Rodrigo. Ver problema P1 abaixo.

### 1.4 Agendamento fora do loop

Crontab do `rodrigor` (relevante): `habit_remind.sh` a cada 30 min;
`habit_weekly.sh` segunda 06:00. Outros: report 08:00, episódios 09:00,
aniversários 09:00, agenda fetch 30/30min. O resto (e-mail, finanças, roteador,
digest, saúde) são systemd timers.

---

## 2. O subsistema de hábitos

### 2.1 Modelo de dados

Um JSON por hábito em `habits/<Pessoa>/<id>.json`, mais um `perfil.json` por
pessoa (dados corporais, ignorado pelos scripts de hábito, usado pelo dashboard).

```jsonc
{
  "id": "h17810559763909", "person": "Rodrigo",
  "type": "weekly_count",          // ou "daily"
  "target_per_week": 1,            // MUTÁVEL pelo próprio agente
  "name": "Exercício físico",
  "cue_time": "07:15", "cue_days": [2,4,5],   // gatilho: ter/qui/sex
  "tiny": "30-45 min ergométrica ou bike em Zona 2 (120-135 bpm)…",  // versão mínima
  "why": "Aumentar VO2 max de 30.5 para 40+…",                       // motivação
  "status": "active",
  "streak_weeks": 0, "miss_streak": 4,
  "last_review_week": "2026-08-17", "last_pace_week": "2026-08-17",  // antirrepetição
  "log": [ {"date":"2026-08-03","done":true,"value":42,"unit":"min","note":"…"} ],
  "adaptations": [ {"date":"…","result":"0/3","change_type":"shrink_target",
                    "assessment":"<análise do Opus>","by":"opus"} ]
}
```

`perfil.json` do Rodrigo: nascimento 1979-12-26, 178 cm; `medicoes[]` (uma só,
2026-06-13: 87,5 kg, IMC 27,6, **VO2max 30,5**); `metas`: VO2 alvo 40, peso alvo
82 kg, FC máx observada 169, **Zona 2 calibrada 120-135 bpm** (não a da fórmula),
Zona 4 144-155.

### 2.2 As cinco peças

| Peça | Quando | O que faz | LLM |
|---|---|---|---|
| `habit.sh` | sob demanda | núcleo CRUD: `create/log/skip/status/list/show/set/adapt` | — |
| `habit_remind.sh` | cron */30min | lembrete no `cue_time` nos `cue_days` (janela ±15 min), barrinha 🟢⚪, `tiny`; pula se já fez hoje; flag em `/tmp`. Também o check-in de domingo 20h | — |
| `habit_coach.sh` | via `process_habits`, qua-sáb | nudge de ritmo quando está atrás (1-2 frases, sem cobrança) | sonnet, **como `pirraikid`** |
| `habit_analyze.sh` | via `process_habits`, domingo | revisão estratégica: manda log+métricas+adaptações anteriores, recebe JSON `{assessment, change_type, new_target, message}`, **aplica no arquivo** | opus, **como `pirraikid`** |
| `habit_weekly.sh` | cron seg 06:00 | fecha a semana, sobe/zera `streak_weeks`, manda retrospectiva | — |

`process_habits()` (telegram_agent.sh:349) é o orquestrador: 1×/dia, só entre 9h
e 22h, gate por `state/habit_last_day`. Domingo → `habit_analyze.sh` (gate
`last_review_week`). Dias 3-6 → `habit_coach.sh pace` se `need > daysleft` ou
(0 feitos e dow≥4), gate `last_pace_week`.

### 2.3 O laço fechado (o que há de mais interessante aqui)

O `habit_analyze.sh` é um **coach que reescreve a própria configuração**. Ele
recebe o histórico inteiro, é instruído a diagnosticar o padrão e a escolher UMA
alavanca, **sem repetir uma que já falhou**, dentre:
`set_anchor | shrink_target | focus_minimum | reframe | change_channel | ask`
(quando não bateu) ou `level_up | none` (quando bateu). O `assessment` fica
gravado em `adaptations[]`, então cada semana ele lê o que já tentou.

O histórico real do hábito de exercício é um bom diário de experimentos:
- **14/06** `set_anchor` → definiu `cue_time` 07:15. **Funcionou**: 1/3 → 2/3, e
  os dois treinos foram Zona 2 de verdade (FC 122 e 117 bpm).
- **21/06** `focus_minimum` (piso inegociável de 2×). **Não segurou**: 0/3.
- **28/06** `ask` (o que quebrou a semana?). Sem resposta registrada no log.
- **05/07** `shrink_target` → meta **3 → 1** ("impossível de falhar", reconstruir
  a sequência e só depois subir).
- Desde então: nada. Última adaptação gravada é 05/07 — ver P1.

### 2.4 Dashboard

`web/habitos/app.py` — Flask, `habit-web.service`, 127.0.0.1:8091, exposto na
:8444 via Tailscale, link na landing (`landing.py`). Login com
`finance_users.json`. Rotas: `/api/status` (semana atual, fase do plano),
`/api/calendar/<ano>/<mes>`, `/api/historico`, `/api/metricas` (12 semanas de
minutos/sessões + medições do perfil), `/api/log` (POST — registra pelo browser).

---

## 3. Estado real hoje (2026-08-27)

- Hábito **Exercício físico**: `target_per_week` = **1**, `streak_weeks` = 0,
  `miss_streak` = 4. Último treino registrado: **03/08** (força, 42 min, 101 bpm
  médio — nem Zona 2 era). Antes dele: 06/07, 16/06, 15/06, 08/06. **6 registros
  em ~11 semanas.**
- Segundo hábito, **Pausas Anti-Sedentarismo** (`type: daily`), criado e nunca
  usado: `log` vazio, `cue_time` vazio, e `process_habits` **ignora** `type` ≠
  `weekly_count`. Está morto por construção.
- VO2 max: uma única medição (30,5 em 13/06). Não há série temporal — o gráfico
  do dashboard tem um ponto só.
- Os lembretes das 07:15 (ter/qui/sex) continuam disparando normalmente.

---

## 4. Problemas conhecidos

**P1 — RESOLVIDO em 27/08 (ver §5). As duas peças de LLM do coach estavam mortas.**
`habit_coach.sh` e `habit_analyze.sh` chamam `sudo -H -u pirraikid claude`, e o
login OAuth do `pirraikid` está **expirado de propósito** desde ~07/08 (commit
c9b82b8; `service_health.sh:162` diz explicitamente que não alerta sobre ele).
Teste feito hoje:

```
$ sudo -H -u pirraikid /usr/local/bin/claude -p --model sonnet "responda: ok"
Failed to authenticate. API Error: 401 OAuth access token has expired.
```

O CLI escreve isso no **stdout** e sai 0, e os scripts só redirecionam stderr
(`2>/dev/null`). Consequências:
1. `habit_analyze.sh` não consegue extrair JSON → **nenhuma adaptação desde
   05/07**, e cai na mensagem hardcoded ("Ei Rodrigo, essa semana o Exercício
   físico não fechou…"). O laço fechado está desligado há ~7 semanas.
2. `habit_coach.sh` devolve **a string do erro 401**, que é não-vazia, então
   `process_habits` **manda o texto do erro para o Telegram** como se fosse o
   nudge. Hoje (qui, 0/1, `last_pace_week` = 17/08) isso dispara na primeira
   passada depois das 9h.
Foi corrigido com as duas coisas: passaram a rodar como `rodrigor` (que está
autenticado; o sandbox `pirraikid` segue valendo só para as personas das filhas)
e ganharam o guard `claude_auth_is_error`. **Consequência a lembrar:** o
`habit_analyze.sh` volta a rodar de verdade no próximo domingo, com 4 semanas de
miss e `target=1` na mesa — a adaptação que ele escolher aí é o próximo dado
interessante, e vale olhar `adaptations[]` depois.

**P2 — Nada alimenta o sistema automaticamente.** Todo registro depende de o
Rodrigo dizer no Telegram que treinou. Os dados ricos que já aparecem nas notas
(FC média, kcal, duração, horário) foram digitados por ele. O Apple Watch/Saúde
não conversa com o Pi. Enquanto isso, o `why` do hábito é medido por um número
(VO2 max) que também só entra à mão — e entrou uma vez só.

**P3 — Métrica errada no lugar da meta.** O hábito conta *sessões* (`done`),
mas o objetivo declarado é fisiológico (VO2 30,5 → 40) e depende de *dose*:
minutos em Zona 2 por semana. Um treino de força de 42 min a 101 bpm conta igual
a 40 min a 125 bpm — e só o segundo move o VO2. O `value/unit` já existe no log
e ninguém usa para julgar a semana.

**P4 — `shrink_target` para 1 pode ter sido armadilha.** Reduzir para 1×/semana
tornou a meta "impossível de falhar", mas também tirou o sinal: com meta 1, o
nudge de ritmo só dispara quinta ou depois, e uma semana com 1 treino conta como
sucesso mesmo sendo dose insuficiente para o objetivo. E, na prática, nem 1
saiu — 4 semanas seguidas de miss. A regra de `level_up` só existe para quem
bate a meta; não há caminho de volta previsto além de um novo `shrink`.

**P5 — Sem canal de entrada para o "por quê não".** O `change_type: ask` foi
escolhido em 28/06, mas ninguém fecha o laço: a pergunta vai pro Telegram e a
resposta do Rodrigo vira contexto do chat, não vira campo no JSON. O
`habit.sh skip <pessoa> <hábito> "<nota>"` existe e nunca é chamado por ninguém
— nem pelo prompt do agente (que só ensina `log`).

**P6 — Duplicação de lógica.** Cálculo de segunda-feira, contagem da semana e
barrinha 🟢⚪ estão reimplementados em `habit.sh`, `habit_remind.sh`,
`habit_weekly.sh`, `process_habits()` e `app.py`. Mudar a regra de "semana"
exige tocar em cinco lugares.

**P7 — Dois relógios de lembrete.** `habit_remind.sh` (cron, gatilho de horário)
e `process_habits` (loop do agente, nudge de ritmo) não se conhecem: dá para
levar o lembrete das 07:15 e o nudge do coach no mesmo dia.

---

## 5. O que já foi corrigido nesta sessão (27/08)

- **Prompt do agente** (`telegram_agent.sh:611`): dizia "meta 3x/semana", que
  está desatualizado desde 05/07 (o próprio `habit_analyze.sh` baixou para 1).
  Agora manda ler a meta de `habit.sh status Rodrigo` e avisa que ela muda
  sozinha. Serviço reiniciado.
- **`plan_phase()`** (`web/habitos/app.py`): usava 106-123 bpm (fórmula) em vez
  da Zona 2 calibrada do `perfil.json`, e avançava de fase por **tempo de
  calendário** — parado desde 03/08, o dashboard já anunciava "Fase 3 —
  Intensidade, 2× HIIT". Agora as faixas vêm do perfil e a fase avança por
  **semanas em que houve treino** (hoje: 4 → Fase 1). O front-end passou a achar
  o hábito por `is_exercise` em vez de `week_num > 0`. `habit-web` reiniciado.
- **P1 — login do coach** (`habit_coach.sh`, `habit_analyze.sh`): saíram do
  `sudo -H -u pirraikid` e rodam como o usuário atual (`rodrigor`), e ambos
  passaram a `source claude_auth.sh` e testar `claude_auth_is_error` na saída —
  o coach **cala** em vez de mandar o 401 como nudge, o analyze marca a falha e
  cai na mensagem de fallback sem gravar adaptação lixo. Os dois marcam
  `claude_auth_mark_ok` quando a resposta é legítima, então o `service_health.sh`
  passa a alertar sobre isso (escopo `rodrigor`, que é vigiado). Testado
  ponta a ponta: o nudge de ritmo voltou a gerar texto de verdade.

---

## 6. Ideias para a próxima sessão

Não implementadas, só como ponto de partida:

1. ~~Consertar P1~~ — feito em 27/08. O coach voltou a falar com o modelo.
2. **Meta em dose, não em contagem**: `target` em minutos-Zona-2 por semana
   (com `value/unit` que já existe), e o log passando a distinguir tipo de treino.
   Exigiria mudar `habit.sh status`, `habit_weekly.sh` e o dashboard juntos (P6).
3. **Fechar o laço de entrada**: ensinar o prompt a usar `habit.sh skip` com a
   nota do motivo quando o Rodrigo disser que não treinou, para o `ask` do
   domingo ter matéria-prima.
4. **Coach context-aware de verdade**: o prompt já manda rodar `agenda.sh free 40 1`
   e propor horário (telegram_agent.sh:624) — mas isso é instrução para o Claude
   do chat, não para o `habit_coach.sh`, que não tem acesso a ferramenta nenhuma
   (é um `claude -p` sem tools, só texto). Dar contexto de agenda ao coach
   proativo é uma mudança de arquitetura pequena e de alto retorno.
5. **Reidratar as medições**: um comando para lançar VO2/peso novos no
   `perfil.json` pelo Telegram — hoje só dá para editar o JSON à mão.
6. **Ressuscitar ou remover** o hábito "Pausas Anti-Sedentarismo" (`type: daily`
   não é tratado por `process_habits`).

## 7. Arquivos para abrir primeiro

```
telegram_agent.sh          # loop (l.455) · process_habits (l.349) · prompt (l.599-658)
habit.sh habit_remind.sh habit_coach.sh habit_analyze.sh habit_weekly.sh
habits/Rodrigo/*.json      # dados + perfil
web/habitos/app.py         # dashboard
claude_auth.sh             # detecção do 401 (chave do P1)
service_health.sh          # o que é vigiado e o que não é
```
