import logging

from flask import Blueprint, current_app, jsonify, make_response, redirect, render_template, request, session, url_for
import mysql.connector
from app.tools.auth import autenticar, bloqueado, limpar_falhas, login_obrigatorio_api, login_obrigatorio_pagina, registrar_falha
from app.db import get_connection

bp = Blueprint("web", __name__)
log = logging.getLogger("agente.web")

MSG_LOGIN_INVALIDO = "E-mail ou senha incorretos."

# ------------------------------------------------------------------ paginas
@bp.get("/")
@login_obrigatorio_pagina
def pagina_chat():
    """Entrega a tela do chat apenas para quem faz login."""
    primeiro_nome = session["nome"].split()[0]
    resposta = make_response(render_template("chat.html", nome=primeiro_nome))
    resposta.headers["Cacha-Control"] = "no-storage"    # o botao "voltar" nao mostra o chat apos sair
    return resposta
    

@bp.get("/login")
def pagina_login():
    if session.get("cliente_id"):
        return redirect(url_for("web.pagina_chat"))
    return render_template("login.html")


# ---------------------------------------------------------------- saude
@bp.get("/health")
def health():
    """Rota simples para confirmar que o servidor esta no ar."""
    return jsonify(status="ok")


@bp.get("/health/db")
def health_db():
    """Confirma que o servidor consegue falar com o banco."""
    try:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
        finally:
            conn.close()
        return jsonify(status="ok")
    except mysql.connector.Error:
        # O detalhe tecnico vai para o log do servidor, nao para quem chamou.
        current_app.logger.exception("Falha ao conectar no banco")
        return jsonify(status="erro", detail="banco indisponivel"), 503


# ------------------------------------------------------------ autenticacao
@bp.post("/api/login")
def login():
    # Só JSON: um formulário de outro site não consegue enviar JSON com o cookie
    if not request.is_json:
        return jsonify(error="Requisição inválida."), 415
    dados = request.get_json(silent=True) or {}
    email, senha = dados.get("email"), dados.get("senha")
    if not isinstance(email,str) or not isinstance(senha, str) or not email.strip() or not senha:
        return jsonify(error="Informe e-mail e senha."), 400
    if len(email) > 200 or len(senha) > 200:
        return jsonify(error="E-mail ou senha longos demais."), 400
    email = email.strip()

    if bloqueado(email):
        return jsonify(error="Muitas tentativas. Aguarde alguns minutos e tente novamente.")
    try:
        cliente = autenticar(email, senha)
    except mysql.connector.Error:
        log.exception("Falha no banco durante o login")
        return jsonify(error="Serviço indisponível no momento. Tente novamente em instantes"), 503
    if cliente is None:
        registrar_falha(email)
        return jsonify(error=MSG_LOGIN_INVALIDO), 401

    limpar_falhas(email)
    session.clear()
    session["cliente_id"], session["nome"] = cliente
    session.permanent = True
    return jsonify(nome=cliente[1])


@bp.post("/api/logout")
def logout():
    if not request.is_json:
        return jsonify(error="Requisição inválida."), 415
    session.clear()
    return jsonify(status="ok")


@bp.get("/api/me")
def quem_sou_eu():
    if session.get("cliente_id"):
        return jsonify(logado=True, nome=session["nome"])
    return jsonify(logado=False)


# -------------------------------------------------------------------- chat
@bp.post("/api/chat")
@login_obrigatorio_api
def chat():
    """Recebe a mensagem do usuário LOGADO e devolve a resposta.

    O cliente ja esta identificado (session["cliente_id"]); quando o agente
    entrar, ele será entregue as ferramentas pelo Contexto.
    """
    if not request.is_json:
        return jsonify(error="Requisição inválida."), 415
    dados = request.get_json(silent=True) or {}
    mensagem = str(dados.get("message", "")).strip()

    # Validacao de entrada.
    if not mensagem:
        return jsonify(error="Mensagem vazia."), 400
    limite = current_app.config["MAX_MENSAGEM"]
    if len(mensagem) > limite:
        return jsonify(error=f"Mensagem acima de {limite} caracteres."), 400

    return jsonify(reply=f"[eco] Voce disse: {mensagem}")

