"""Autenticação: login/logout, troca de senha e raiz."""
import os, subprocess
from flask import Blueprint, request, session, redirect, url_for, flash, render_template
from werkzeug.security import check_password_hash

from core import ROOT, users, login_required

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("user", "").strip(); p = request.form.get("pw", "")
        rec = users().get(u)
        if rec and check_password_hash(rec["hash"], p):
            session["user"] = u; session["role"] = rec.get("role", "editor")
            return redirect(request.args.get("next") or url_for("dash.financas"))
        flash("Usuário ou senha inválidos.")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear(); return redirect(url_for("auth.home"))


@bp.route("/")
def home():
    return redirect(url_for("dash.financas"))  # raiz das Finanças vai direto pro Resumo (landing do PIrrai é a raiz do tailnet)


@bp.route("/senha", methods=["GET", "POST"])
@login_required
def senha():
    if request.method == "POST":
        atual = request.form.get("atual", ""); nova = request.form.get("nova", "")
        rec = users().get(session["user"])
        if not (rec and check_password_hash(rec["hash"], atual)):
            flash("Senha atual incorreta.")
        elif len(nova) < 6:
            flash("Nova senha muito curta (mín. 6).")
        else:
            subprocess.run(["python3", os.path.join(ROOT, "finance_user.py"),
                            "set", session["user"], session.get("role", "editor"), nova])
            flash("Senha alterada.")
        return redirect(url_for("auth.senha"))
    return render_template("senha.html")
