-- habitos/schema.sql — registro do sistema de hábitos (fatia 1).
--
-- REGRA CENTRAL: `eventos` é append-only e é a VERDADE. `metricas` e todas as
-- views são derivadas — dá para jogar fora e reconstruir a partir dos eventos.
-- Nada além de registro.py escreve aqui.
--
-- Datas: tudo em hora LOCAL (America/Recife), no formato 'YYYY-MM-DD HH:MM:SS'.
-- `ts` = quando foi registrado; `data` = o dia a que o fato se refere (podem
-- divergir: registrar hoje um treino de ontem é normal).

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS eventos (
  id      INTEGER PRIMARY KEY,
  ts      TEXT NOT NULL,
  data    TEXT NOT NULL,
  habito  TEXT NOT NULL,
  tipo    TEXT NOT NULL,   -- sessao | falha | lembrete | resposta | silencio
                           -- | estrategia_ativada | avaliacao | proposta
                           -- | decisao_humana | pausa_inicio | pausa_fim
  origem  TEXT NOT NULL,   -- telegram | dashboard | rotina | coach | migracao | manual
  payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_eventos_habito_data ON eventos(habito, data);
CREATE INDEX IF NOT EXISTS ix_eventos_tipo        ON eventos(habito, tipo, data);

-- Formato longo de propósito: métrica nova não exige migração de schema.
-- `classe` é uma DICA (adesao = a rotina aconteceu; resultado = o objetivo se
-- moveu; contexto = o resto). Quem decide de verdade o que conta como adesão e
-- como resultado é o criterio_sucesso da estratégia corrente, não esta coluna.
CREATE TABLE IF NOT EXISTS metricas (
  id        INTEGER PRIMARY KEY,
  ts        TEXT NOT NULL,
  data      TEXT NOT NULL,
  habito    TEXT NOT NULL,
  campo     TEXT NOT NULL,
  valor_num REAL,
  valor_txt TEXT,
  unidade   TEXT,
  classe    TEXT NOT NULL DEFAULT 'contexto',
  -- como a métrica se agrega no tempo. Sem isto, a view somava peso e VO2 ao
  -- longo da semana (87 kg + 87 kg = 174 kg): dose se soma, medição não.
  agregacao TEXT NOT NULL DEFAULT 'soma',   -- soma | media | ultimo
  fonte     TEXT NOT NULL,
  evento_id INTEGER REFERENCES eventos(id)
);
CREATE INDEX IF NOT EXISTS ix_metricas_campo ON metricas(habito, campo, data);

-- O arquivo em habitos/estrategias/ é a fonte de verdade da estratégia; esta
-- tabela é a LINHA DO TEMPO (que versão estava no ar quando), para dar join com
-- eventos e métricas na hora de julgar se a estratégia funcionou.
CREATE TABLE IF NOT EXISTS estrategias (
  habito    TEXT NOT NULL,
  versao    INTEGER NOT NULL,
  ativa_de  TEXT NOT NULL,
  ativa_ate TEXT,              -- NULL = é a corrente
  arquivo   TEXT NOT NULL,
  hash      TEXT,
  autor     TEXT,              -- coach | rodrigo
  hipotese  TEXT,
  desfecho  TEXT,              -- preenchido quando sai do ar: sucesso|falha|abandono
  PRIMARY KEY (habito, versao)
);

-- O placar do próprio coach: sem isto ele teoriza bonito e nunca aprende.
CREATE TABLE IF NOT EXISTS avaliacoes (
  id        INTEGER PRIMARY KEY,
  ts        TEXT NOT NULL,
  habito    TEXT NOT NULL,
  versao    INTEGER,
  adesao    REAL,
  resultado REAL,
  quadrante TEXT,     -- ok | dose_insuficiente | nao_cabe | ruido
  decisao   TEXT,
  aplicada  INTEGER NOT NULL DEFAULT 0,
  motivo    TEXT,
  payload   TEXT NOT NULL DEFAULT '{}'
);

-- ── views ────────────────────────────────────────────────────────────────────
-- A ÚNICA definição de "semana" do sistema (segunda como primeiro dia). Antes
-- isto estava reimplementado em cinco arquivos diferentes.
DROP VIEW IF EXISTS v_eventos;
CREATE VIEW v_eventos AS
  SELECT *, date(data, '-' || ((strftime('%w', data) + 6) % 7) || ' days') AS semana
  FROM eventos;

DROP VIEW IF EXISTS v_metricas;
CREATE VIEW v_metricas AS
  SELECT *, date(data, '-' || ((strftime('%w', data) + 6) % 7) || ' days') AS semana
  FROM metricas;

-- sessoes = dias distintos com treino (é o que "3x por semana" quer dizer);
-- registros = quantos eventos, para o caso de mais de uma sessão no mesmo dia.
DROP VIEW IF EXISTS v_sessoes_semanais;
CREATE VIEW v_sessoes_semanais AS
  SELECT habito, semana, COUNT(DISTINCT data) AS sessoes, COUNT(*) AS registros
  FROM v_eventos WHERE tipo = 'sessao' GROUP BY habito, semana;

DROP VIEW IF EXISTS v_metricas_semanais;
CREATE VIEW v_metricas_semanais AS
  SELECT m.habito, m.semana, m.campo, m.unidade, m.classe, m.agregacao,
         SUM(m.valor_num) AS soma, AVG(m.valor_num) AS media, COUNT(*) AS n,
         (SELECT m2.valor_num FROM v_metricas m2
           WHERE m2.habito = m.habito AND m2.campo = m.campo AND m2.semana = m.semana
             AND m2.valor_num IS NOT NULL
           ORDER BY m2.data DESC, m2.id DESC LIMIT 1) AS ultimo,
         -- o valor que vale para esta métrica, já escolhido pela agregação
         CASE m.agregacao
           WHEN 'media'  THEN AVG(m.valor_num)
           WHEN 'ultimo' THEN (SELECT m2.valor_num FROM v_metricas m2
                                WHERE m2.habito = m.habito AND m2.campo = m.campo
                                  AND m2.semana = m.semana AND m2.valor_num IS NOT NULL
                                ORDER BY m2.data DESC, m2.id DESC LIMIT 1)
           ELSE SUM(m.valor_num) END AS valor
  FROM v_metricas m WHERE m.valor_num IS NOT NULL
  GROUP BY m.habito, m.semana, m.campo, m.unidade, m.classe, m.agregacao;

-- A distribuição de obstáculos é o que separa "reduzir a meta" de "trocar o
-- gatilho". Silêncio NÃO entra aqui: silêncio é desconhecido, não é falha.
DROP VIEW IF EXISTS v_obstaculos_semanais;
CREATE VIEW v_obstaculos_semanais AS
  SELECT habito, semana,
         COALESCE(json_extract(payload, '$.obstaculo'), 'nao_informado') AS obstaculo,
         COUNT(*) AS n
  FROM v_eventos WHERE tipo = 'falha' GROUP BY habito, semana, obstaculo;
