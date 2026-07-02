"""Migrações de schema versionadas (substitui o _ensure_schema silencioso).

Cada migração é idempotente (checa a existência da coluna antes do ALTER) e roda
uma única vez — o nome fica registrado em schema_migrations. Falha é LOGADA
(não mais engolida com `except: pass`); o app segue no ar com o schema anterior."""
import logging

log = logging.getLogger("finance.migrations")


def _cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def m_accounts_titular(con):
    cols = _cols(con, "accounts")
    if cols and "titular" not in cols:
        con.execute("ALTER TABLE accounts ADD COLUMN titular TEXT")
        con.execute("UPDATE accounts SET titular='Ayla'    WHERE titular IS NULL AND lower(name) LIKE '%ayla%'")
        con.execute("UPDATE accounts SET titular='Rodrigo' WHERE titular IS NULL AND lower(name) LIKE '%rodrigo%'")


def m_tx_split_group(con):
    cols = _cols(con, "transactions")
    if cols and "split_group" not in cols:  # lançamento composto: liga as partes de uma divisão
        con.execute("ALTER TABLE transactions ADD COLUMN split_group INTEGER")


def m_rules_ranges(con):
    cols = _cols(con, "rules")  # regras por faixa de dias/conta/favorecido
    if not cols: return
    for cn, ct in (("dom_min", "INTEGER"), ("dom_max", "INTEGER"), ("account_id", "INTEGER"), ("set_fav", "TEXT")):
        if cn not in cols: con.execute(f"ALTER TABLE rules ADD COLUMN {cn} {ct}")


def m_accounts_iof(con):
    cols = _cols(con, "accounts")  # IOF/spread: taxa-padrão por conta (contas globais)
    if not cols: return
    for cn in ("iof_rate", "spread_rate"):
        if cn not in cols: con.execute(f"ALTER TABLE accounts ADD COLUMN {cn} REAL DEFAULT 0")


def m_accounts_orcamento(con):
    cols = _cols(con, "accounts")
    if cols and "entra_orcamento" not in cols:  # conta entra no orçamento (receitas/despesas/teto)?
        con.execute("ALTER TABLE accounts ADD COLUMN entra_orcamento INTEGER DEFAULT 1")
        # contas globais (não-BRL) e de investimento ficam fora por padrão
        con.execute("UPDATE accounts SET entra_orcamento=0 WHERE COALESCE(currency,'BRL')<>'BRL' OR lower(COALESCE(type,'')) LIKE '%invest%'")


def m_tx_iof(con):
    cols = _cols(con, "transactions")  # centavos; breakdown da conversão (perna em BRL)
    if not cols: return
    for cn in ("iof_amount", "spread_amount"):
        if cn not in cols: con.execute(f"ALTER TABLE transactions ADD COLUMN {cn} INTEGER")


def m_tx_transfer_group(con):
    cols = _cols(con, "transactions")
    if cols and "transfer_group" not in cols:  # UUID compartilhado entre as duas pernas
        con.execute("ALTER TABLE transactions ADD COLUMN transfer_group TEXT")


MIGRATIONS = [
    ("accounts-titular", m_accounts_titular),
    ("tx-split-group", m_tx_split_group),
    ("rules-ranges", m_rules_ranges),
    ("accounts-iof", m_accounts_iof),
    ("accounts-orcamento", m_accounts_orcamento),
    ("tx-iof", m_tx_iof),
    ("tx-transfer-group", m_tx_transfer_group),
]


def migrate(con):
    con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
        name TEXT PRIMARY KEY, applied_at TEXT DEFAULT (datetime('now')))""")
    done = {r[0] for r in con.execute("SELECT name FROM schema_migrations")}
    for name, fn in MIGRATIONS:
        if name in done: continue
        try:
            fn(con)
            con.execute("INSERT INTO schema_migrations(name) VALUES(?)", (name,))
            con.commit()
            log.info("migração aplicada: %s", name)
        except Exception:
            con.rollback()
            log.exception("migração FALHOU (app segue com schema anterior): %s", name)
