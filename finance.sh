#!/bin/bash
# finance.sh — núcleo do módulo de finanças do PIrrai (SQLite).
# Valores monetários SEMPRE em CENTAVOS (INTEGER). Nunca float.
# Comandos: init | accounts | add | list | categorize | autocat | summary
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DB="${FINANCE_DB:-$DIR/finance.db}"
sq(){ sqlite3 "$DB" "$@"; }

# reais -> centavos (aceita "45", "45,90", "45.90", "R$ 45,90", "-12,5")
to_cents(){
  local v="${1//R\$/}"; v="${v// /}"; v="${v//./}"; v="${v//,/.}"
  awk -v x="$v" 'BEGIN{ if(x=="" ){print "ERR"; exit} printf "%d\n", (x*100 + (x<0?-0.5:0.5)) }'
}
cents_fmt(){ awk -v c="$1" 'BEGIN{ printf "R$ %.2f", c/100 }' | sed 's/\./,/'; }

init_db(){
  sq <<'SQL'
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, type TEXT DEFAULT 'credito',
  bank TEXT, color TEXT DEFAULT '#888', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, parent TEXT,
  icon TEXT, color TEXT, grupo TEXT, rule_keywords TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL, time TEXT,
  amount INTEGER NOT NULL,                 -- centavos; negativo = despesa, positivo = receita
  description TEXT, merchant TEXT,
  category TEXT, subcategory TEXT,
  account_id INTEGER REFERENCES accounts(id),
  source TEXT DEFAULT 'manual',            -- manual|telegram|email|ofx
  status TEXT DEFAULT 'confirmado',        -- pendente|confirmado|conciliado|importado|agendado
  notes TEXT,
  installment_id INTEGER,
  external_id TEXT,                         -- FITID do OFX
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_external ON transactions(external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE TABLE IF NOT EXISTS budgets(
  id INTEGER PRIMARY KEY, category TEXT, month TEXT, limit_amount INTEGER,
  UNIQUE(category,month));
CREATE TABLE IF NOT EXISTS installments(
  id INTEGER PRIMARY KEY, total INTEGER, amount INTEGER, n_total INTEGER, n_current INTEGER,
  start_date TEXT, description TEXT, account_id INTEGER);
CREATE TABLE IF NOT EXISTS ofx_imports(
  id INTEGER PRIMARY KEY, filename TEXT, imported_at TEXT DEFAULT (datetime('now','localtime')),
  matched INTEGER DEFAULT 0, unmatched INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS budget_alerts(
  category TEXT, month TEXT, level INTEGER, sent_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(category,month,level));
SQL
}

migrate_cols(){  # adiciona coluna grupo em bancos já existentes
  sq "PRAGMA table_info(categories);" | grep -q '|grupo|' || sq "ALTER TABLE categories ADD COLUMN grupo TEXT;"
}

seed_categories(){
  # name|parent|icon|color|grupo|keywords(csv)  — grupo só é aplicado se a categoria ainda não tiver um (preserva customização)
  while IFS='|' read -r name parent icon color grupo kws; do
    [ -z "$name" ] && continue
    local jkw; jkw=$(printf '%s' "$kws" | jq -Rc 'split(",")|map(select(length>0))')
    sq "INSERT INTO categories(name,parent,icon,color,grupo,rule_keywords)
        VALUES('$name','$parent','$icon','$color','$(esc "$grupo")','$(printf '%s' "$jkw" | sed "s/'/''/g")')
        ON CONFLICT(name) DO UPDATE SET grupo=COALESCE(categories.grupo, excluded.grupo);"
  done <<'CATS'
Mercado||🛒|#2e7d32|Casa|mercado,supermercado,atacad,carrefour,pao de acucar,assai,big,extra,hortifruti
Alimentação||🍔|#ef6c00|Alimentação|ifood,rappi,uber eats,restaurante,padaria,lanche,delivery,bar,cafe
Transporte||🚗|#1565c0|Transporte|uber,99app,99 tecnologia,taxi,posto,gasolina,combustivel,estacionamento,pedagio,metro
Compras||🛍️|#6a1b9a|Pessoal|amazon,mercadolivre,mercado livre,magazine,americanas,shopee,aliexpress,shein
Assinaturas||📺|#c62828|Pessoal|netflix,spotify,youtube,prime,hbo,max,disney,apple.com,google,icloud,chatgpt,openai,claude
Saúde||💊|#00838f|Saúde|farmacia,drogaria,droga,hospital,clinica,laboratorio,unimed,medico,dentista
Casa||🏠|#5d4037|Casa|aluguel,condominio,luz,energia,enel,agua,gas,internet,vivo,claro,tim,net
Educação||📚|#283593|Pessoal|escola,curso,faculdade,livro,udemy,alura
Lazer||🎬|#ad1457|Lazer|cinema,ingresso,viagem,hotel,airbnb,booking,show
Serviços||🔧|#455a64|Casa|barbearia,salao,lavanderia,assinatura,mensalidade
Receitas||💰|#1b5e20|Receitas|salario,pagamento,deposito,pix recebido,rendimento,transferencia recebida
Outros||📌|#757575|Outros|
CATS
}

# escapa string p/ SQL
esc(){ printf '%s' "$1" | sed "s/'/''/g"; }

# autocat_match "texto" -> categoria cujo rule_keywords casa (substring, case-insensitive); vazio se nenhuma
deburr(){ printf '%s' "$1" | iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null | tr '[:upper:]' '[:lower:]'; }
autocat_match(){
  local txt; txt=$(deburr "$1")
  [ -z "$txt" ] && return
  sq -separator $'\t' "SELECT name,rule_keywords FROM categories WHERE rule_keywords<>'[]';" | \
  while IFS=$'\t' read -r name kws; do
    while IFS= read -r kw; do
      kw=$(deburr "$kw")
      [ -n "$kw" ] && case "$txt" in *"$kw"*) echo "$name"; return;; esac
    done < <(printf '%s' "$kws" | jq -r '.[]')
  done | head -1
}

cmd="${1:-help}"; shift 2>/dev/null || true
case "$cmd" in
  init)
    init_db; migrate_cols; seed_categories
    echo "OK — finance.db pronto ($(sq 'SELECT COUNT(*) FROM categories;') categorias). Caminho: $DB"
    ;;

  group)  # group "<categoria>" "<grupo>"
    cat="${1:?uso: group \"categoria\" \"grupo\"}"; grp="${2:?grupo}"
    sq "UPDATE categories SET grupo='$(esc "$grp")' WHERE name='$(esc "$cat")';"
    echo "OK — $cat → grupo $grp"
    ;;

  limit)  # limit "<categoria>" <reais|->   (limite mensal recorrente; '-' remove)
    cat="${1:?uso: limit \"categoria\" <valor|->}"; val="${2:?valor ou -}"
    if [ "$val" = "-" ]; then
      sq "DELETE FROM budgets WHERE category='$(esc "$cat")' AND month='*';
          DELETE FROM budget_alerts WHERE category='$(esc "$cat")';"
      echo "OK — limite removido de $cat"
    else
      cents=$(to_cents "$val"); [ "$cents" = "ERR" ] && { echo "valor inválido"; exit 1; }; cents=${cents#-}
      sq "INSERT INTO budgets(category,month,limit_amount) VALUES('$(esc "$cat")','*',$cents)
          ON CONFLICT(category,month) DO UPDATE SET limit_amount=excluded.limit_amount;
          DELETE FROM budget_alerts WHERE category='$(esc "$cat")' AND month='$(date +%Y-%m)';"
      echo "OK — limite de $cat: $(cents_fmt "$cents")/mês"
    fi
    ;;

  limits)  # limits [YYYY-MM] : categoria|limite|gasto|pct
    mon="${1:-$(date +%Y-%m)}"
    sq -separator '|' "SELECT b.category, b.limit_amount,
        COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=b.category AND amount<0 AND substr(date,1,7)='$mon'),0) AS spent,
        CASE WHEN b.limit_amount>0 THEN CAST(COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=b.category AND amount<0 AND substr(date,1,7)='$mon'),0)*100/b.limit_amount AS INT) ELSE 0 END AS pct
        FROM budgets b WHERE b.month='*' ORDER BY pct DESC;"
    ;;

  groups)  # groups [YYYY-MM] : despesas agrupadas
    mon="${1:-$(date +%Y-%m)}"
    echo "Despesas por grupo ($mon):"
    sq -separator '|' "SELECT COALESCE(c.grupo,'(sem grupo)'), printf('R\$ %.2f',-SUM(t.amount)/100.0)
        FROM transactions t LEFT JOIN categories c ON c.name=t.category
        WHERE t.amount<0 AND substr(t.date,1,7)='$mon'
        GROUP BY c.grupo ORDER BY SUM(t.amount) ASC;"
    ;;

  accounts)
    sub="${1:-list}"; shift 2>/dev/null || true
    case "$sub" in
      add)  # accounts add "Nome" [tipo] [banco] [cor]
        name="${1:?uso: accounts add \"Nome\" [tipo] [banco] [cor]}"; type="${2:-credito}"; bank="${3:-}"; color="${4:-#888}"
        sq "INSERT OR IGNORE INTO accounts(name,type,bank,color) VALUES('$(esc "$name")','$(esc "$type")','$(esc "$bank")','$(esc "$color")');"
        echo "OK — conta: $name ($type${bank:+/$bank})"
        ;;
      list|*)
        echo "id|nome|tipo|banco|cor"
        sq -separator '|' "SELECT id,name,type,COALESCE(bank,''),color FROM accounts ORDER BY id;"
        ;;
    esac
    ;;

  add)  # add <valor> "descrição" [categoria] [conta_id] [data] [--receita]
    val="${1:?uso: add <valor> \"descrição\" [categoria] [conta] [data]}"; desc="${2:-}"; cat="${3:-}"; acc="${4:-}"; dt="${5:-}"
    receita=0; for a in "$@"; do [ "$a" = "--receita" ] && receita=1; done
    cents=$(to_cents "$val"); [ "$cents" = "ERR" ] && { echo "valor inválido: $val"; exit 1; }
    # despesa por padrão (negativo); receita fica positiva
    if [ "$receita" = "1" ]; then cents=${cents#-}; else [ "${cents:0:1}" != "-" ] && cents="-$cents"; fi
    [ -z "$dt" ] && dt=$(date +%F)
    # auto-categoriza se não veio categoria
    if [ -z "$cat" ]; then cat=$(autocat_match "$desc"); fi
    accsql="NULL"; [ -n "$acc" ] && accsql="$acc"
    id=$(sq "INSERT INTO transactions(date,amount,description,category,account_id,source,status)
        VALUES('$(esc "$dt")',$cents,'$(esc "$desc")',$([ -n "$cat" ] && echo "'$(esc "$cat")'" || echo NULL),$accsql,'${SOURCE:-manual}','confirmado');
        SELECT last_insert_rowid();")
    echo "OK #$id — $(cents_fmt "$cents") · ${desc:-(sem descrição)}${cat:+ · $cat} · $dt"
    ;;

  list)  # list [YYYY-MM]   (default: mês atual)
    mon="${1:-$(date +%Y-%m)}"
    echo "id|data|valor|descrição|categoria|conta|status"
    sq -separator '|' "SELECT t.id,t.date, printf('R\$ %.2f',t.amount/100.0), COALESCE(t.description,''),
        COALESCE(t.category,'—'), COALESCE(a.name,'—'), t.status
        FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        WHERE substr(t.date,1,7)='$mon' ORDER BY t.date DESC, t.id DESC;"
    ;;

  categorize)  # categorize <id> <categoria>
    id="${1:?uso: categorize <id> <categoria>}"; cat="${2:?categoria}"
    sq "UPDATE transactions SET category='$(esc "$cat")' WHERE id=$id;"
    echo "OK — #$id → $cat"
    ;;

  autocat)  # autocat "texto"  -> imprime categoria sugerida (vazio se nenhuma)
    autocat_match "${1:-}"
    ;;

  summary)  # summary [YYYY-MM]
    mon="${1:-$(date +%Y-%m)}"
    echo "Mês $mon"
    echo "Despesas: $(cents_fmt "$(sq "SELECT COALESCE(-SUM(amount),0) FROM transactions WHERE amount<0 AND substr(date,1,7)='$mon';")")"
    echo "Receitas: $(cents_fmt "$(sq "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE amount>0 AND substr(date,1,7)='$mon';")")"
    echo "Por categoria (despesas):"
    sq -separator '|' "SELECT COALESCE(category,'—'), printf('R\$ %.2f',-SUM(amount)/100.0)
        FROM transactions WHERE amount<0 AND substr(date,1,7)='$mon'
        GROUP BY category ORDER BY SUM(amount) ASC;"
    ;;

  *) echo "uso: finance.sh {init|accounts|add|list|categorize|autocat|summary}";;
esac
