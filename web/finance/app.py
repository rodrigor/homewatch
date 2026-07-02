#!/usr/bin/env python3
"""Finanças PIrrai — entry point (systemd roda `python3 app.py`).
A lógica vive nos módulos: core (factory/helpers), migrations e bp_* (blueprints).
Bind em 127.0.0.1:8090 (dados financeiros NÃO ficam expostos na LAN; acesso via VPN/SSH-tunnel)."""
import os, sys, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
app = create_app()

if __name__ == "__main__":
    # bind só em localhost; exposição segura é feita pelo `tailscale serve` (HTTPS, só no tailnet).
    app.run(host="127.0.0.1", port=8090, threaded=True)
