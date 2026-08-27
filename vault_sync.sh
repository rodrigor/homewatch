#!/bin/bash
# vault_sync.sh — NEUTRALIZADO em 2026-08-23.
#
# O vault deixou de ser repositório git (nem aqui, nem no Mac) e o remote
# rodrigor/home foi aposentado. Este script commitava e empurrava pra lá;
# manter isso vivo só empurraria pra um repo morto.
#
# Continua existindo como no-op porque anota.sh e telegram_agent.sh o chamam.
# Para levar arquivos ao Mac, salve em ~/dropped — o Rodrigo puxa com dropped-pull.
echo "vault_sync: desativado (vault não é mais repo git). Para enviar ao Mac, salve em ~/dropped."
exit 0
