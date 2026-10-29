"""Autenticacao do cliente: senha com hash, limite de tentativas e protecao de rotas."""
import time
from functools import wraps
from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from app.db import get_connection

MAX_FALHAS = 5               # tentativas erradas permitidas...
JANELA_SEGUNDOS = 300        # dentro de 5 minutos, para o mesmo e-mail e o mesmo computador

# Falhas recentes, guardadas na MEMÓRIA do processo: serve para a demonstração local
_falhas: dict[str, list[float]] = {}

# Hash de uma senha que ninguém usa: quando o e-mail nao existe, conferimos contra ele
# só para gastar o mesmo tempo. Assim o tempo de resposta não revela quais e-mails existem.
_HASH_FALSO = generate_password_hash("senha-que-ninguem-usa")


def _chave(email: str) -> str:
    return f"{email.strip().lower()}|{request.remote_addr}"


def bloqueado(email: str) -> bool:
    agora = time.time()
    recentes = [t for t in _falhas.get(_chave(email), []) if agora - t < JANELA_SEGUNDOS]
    _falhas[_chave(email)] = recentes
    return len(recentes) >= MAX_FALHAS


def registrar_falha(email: str) -> None:
    _falhas.setdefault(_chave(email), []).append(time.time())


def limpar_falhas(email: str) -> None:
    _falhas.pop(_chave(email), None)


def autenticar(email: str, senha: str):
    """Devolve (id, nome) se o par e-mail/senha estiver certo; senão, None.

    A resposta não diz SE o erro foi no e-mail ou na senha.
    """
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, nome, senha_hash FROM cliente WHERE email = %s", (email,))
        cliente = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    hash_guardado = cliente["senha_hash"] if cliente and cliente["senha_hash"] else None
    senha_certa = check_password_hash(hash_guardado or _HASH_FALSO, senha)
    if hash_guardado and senha_certa:
        return cliente["id"], cliente["nome"]
    return None


def login_obrigatorio_api(funcao):
    """Rotas de API: sem login, responde 401 em JSON."""
    @wraps(funcao)
    def interna(*args, **kwargs):
        if not session.get("cliente_id"):
            return jsonify(error="Sua sessão expirou. Faça login novamente."), 401
        return funcao(*args, **kwargs)
    return interna


def login_obrigatorio_pagina(funcao):
    """Páginas: sem login, manda para a tela de login."""
    @wraps(funcao)
    def interna(*args, **kwargs):
        if not session.get("cliente_id"):
            return redirect(url_for("web.pagina_login"))
        return funcao(*args, **kwargs)
    return interna