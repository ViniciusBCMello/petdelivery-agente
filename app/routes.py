from flask import Blueprint, current_app, jsonify, render_template, request
import mysql.connector

from .db import get_connection

bp = Blueprint("web", __name__)


@bp.get("/")
def pagina_chat():
    """Entrega a tela do chat."""
    return render_template("chat.html")


@bp.get("/health")
def health():
    """Rota simples para confirmar que o servidor esta no ar."""
    return jsonify(status="ok")


@bp.post("/api/chat")
def chat():
    """Recebe a mensagem do usuario e devolve a resposta.

    PASSO 1: ainda nao ha agente. A resposta e um eco, so para provar
    que o caminho navegador -> servidor -> navegador funciona.
    """
    dados = request.get_json(silent=True) or {}
    mensagem = str(dados.get("message", "")).strip()

    # Validacao de entrada: nunca confie no que chega do cliente.
    if not mensagem:
        return jsonify(error="Mensagem vazia."), 400
    limite = current_app.config["MAX_MENSAGEM"]
    if len(mensagem) > limite:
        return jsonify(error=f"Mensagem acima de {limite} caracteres."), 400

    return jsonify(reply=f"[eco] Voce disse: {mensagem}")

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