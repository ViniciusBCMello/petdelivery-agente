import json

import pytest

from app import auth
from app.tools import executar

SENHA_DEMO = "pet123"        # a senha que scripts/definir_senhas.py grava por padrao


@pytest.fixture()
def http(app):
    """Navegador de teste (guarda cookies). Zera o contador de tentativas antes e depois."""
    auth._falhas.clear()
    with app.test_client() as navegador:
        yield navegador
    auth._falhas.clear()


@pytest.fixture()
def cliente_demo(ctx):
    cur = ctx.conn.cursor()
    cur.execute("SELECT id, nome, email FROM cliente WHERE senha_hash IS NOT NULL ORDER BY id LIMIT 1")
    linha = cur.fetchone()
    cur.close()
    if linha is None:
        pytest.skip("rode scripts/definir_senhas.py para criar as senhas de demonstracao")
    return {"id": linha[0], "nome": linha[1], "email": linha[2]}


def entrar(http, email, senha):
    return http.post("/api/login", json={"email": email, "senha": senha})


# ================================================================= paginas
def test_pagina_do_chat_sem_login_redireciona_para_o_login(http):
    r = http.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")


def test_tela_de_login_abre_sem_login(http):
    r = http.get("/login")
    assert r.status_code == 200 and b'id="form-login"' in r.data


def test_com_login_o_chat_abre_e_a_tela_de_login_redireciona(http, cliente_demo):
    assert entrar(http, cliente_demo["email"], SENHA_DEMO).status_code == 200
    chat = http.get("/")
    assert chat.status_code == 200 and cliente_demo["nome"].split()[0].encode() in chat.data
    assert chat.headers["Cache-Control"] == "no-store"
    assert http.get("/login").status_code == 302


# =================================================================== login
def test_login_correto_devolve_o_nome_e_cria_a_sessao(http, cliente_demo):
    r = entrar(http, cliente_demo["email"], SENHA_DEMO)
    assert r.status_code == 200 and r.get_json()["nome"] == cliente_demo["nome"]
    assert http.get("/api/me").get_json() == {"logado": True, "nome": cliente_demo["nome"]}


def test_login_com_senha_errada_e_com_email_inexistente_dao_a_mesma_resposta(http, cliente_demo):
    errada = entrar(http, cliente_demo["email"], "senha-errada")
    inexistente = entrar(http, "ninguem@example.com", "senha-errada")
    assert errada.status_code == inexistente.status_code == 401
    assert errada.get_json() == inexistente.get_json()      # nao revela se o e-mail existe
    assert http.get("/api/me").get_json() == {"logado": False}


def test_cookie_de_sessao_tem_as_protecoes(http, cliente_demo):
    cookies = entrar(http, cliente_demo["email"], SENHA_DEMO).headers.getlist("Set-Cookie")
    sessao = next(c for c in cookies if c.startswith("session="))
    assert "HttpOnly" in sessao and "SameSite=Lax" in sessao


def test_hash_da_senha_nunca_sai_do_servidor(http, ctx, como_cliente, cliente_demo):
    resposta = entrar(http, cliente_demo["email"], SENHA_DEMO).get_data(as_text=True)
    me = http.get("/api/me").get_data(as_text=True)
    perfil = json.dumps(executar("consultar_meu_perfil", {}, como_cliente(cliente_demo["id"])))
    for texto in (resposta, me, perfil):
        assert "scrypt" not in texto and "senha_hash" not in texto


def test_login_descarta_a_sessao_anterior(http, cliente_demo):
    with http.session_transaction() as sessao:
        sessao["lixo"] = "valor-de-uma-sessao-anterior"
    entrar(http, cliente_demo["email"], SENHA_DEMO)
    with http.session_transaction() as sessao:
        assert "lixo" not in sessao and sessao["cliente_id"] == cliente_demo["id"]


def test_entrada_invalida_no_login(http):
    for corpo in ({}, {"email": "a@b.com"}, {"senha": "x"}, {"email": "", "senha": "x"},
                  {"email": 5, "senha": "x"}, {"email": "a@b.com", "senha": ["x"]},
                  {"email": "a" * 201, "senha": "x"}, {"email": "a@b.com", "senha": "x" * 201}):
        assert http.post("/api/login", json=corpo).status_code == 400, corpo


def test_login_exige_json(http, cliente_demo):
    r = http.post("/api/login", data={"email": cliente_demo["email"], "senha": SENHA_DEMO})   # formulario
    assert r.status_code == 415


def test_limite_de_tentativas_bloqueia_a_forca_bruta(http, cliente_demo):
    for _ in range(auth.MAX_FALHAS):
        assert entrar(http, cliente_demo["email"], "errada").status_code == 401
    assert entrar(http, cliente_demo["email"], "errada").status_code == 429
    assert entrar(http, cliente_demo["email"], SENHA_DEMO).status_code == 429       # nem a senha certa entra
    assert entrar(http, "outro@example.com", "errada").status_code == 401           # outro e-mail nao e afetado


def test_login_certo_zera_o_contador_de_falhas(http, cliente_demo):
    for _ in range(auth.MAX_FALHAS - 1):
        entrar(http, cliente_demo["email"], "errada")
    assert entrar(http, cliente_demo["email"], SENHA_DEMO).status_code == 200
    for _ in range(auth.MAX_FALHAS - 1):
        assert entrar(http, cliente_demo["email"], "errada").status_code == 401      # recomecou do zero


# =================================================================== chat
def test_chat_sem_login_e_recusado(http):
    r = http.post("/api/chat", json={"message": "oi"})
    assert r.status_code == 401 and "login" in r.get_json()["error"].lower()


def test_chat_com_login_responde_e_valida_a_mensagem(http, cliente_demo):
    entrar(http, cliente_demo["email"], SENHA_DEMO)
    assert http.post("/api/chat", json={"message": "oi"}).get_json()["reply"].startswith("[eco]")
    assert http.post("/api/chat", json={"message": "   "}).status_code == 400
    assert http.post("/api/chat", json={"message": "a" * 1001}).status_code == 400
    assert http.post("/api/chat", data="oi").status_code == 415


# ================================================================== logout
def test_logout_encerra_a_sessao(http, cliente_demo):
    entrar(http, cliente_demo["email"], SENHA_DEMO)
    assert http.post("/api/logout", json={}).get_json() == {"status": "ok"}
    assert http.get("/api/me").get_json() == {"logado": False}
    assert http.post("/api/chat", json={"message": "oi"}).status_code == 401
    assert http.get("/").status_code == 302


def test_logout_exige_json(http):
    assert http.post("/api/logout", data="x").status_code == 415