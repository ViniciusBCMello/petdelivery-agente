"""A rota /api/chat com o agente ligado (LLM de mentira): sessão, histórico, erros e conexão."""
import mysql.connector
import pytest
from test_falsos import ProvedorFalso, texto, chama

from app import auth, routes
from app.agente.historico import Historico
from app.agente.orquestrador import Agente
from app.agente.provedor import ErroProvedor

SENHA_DEMO = "pet123"


class Espiao:
    """Executor de mentira que anota o Contexto recebido."""
    def __init__(self):
        self.contextos = []

    def __call__(self, nome, argumentos, ctx):
        self.contextos.append(ctx)
        return {"ok": True, "dados": {}}


@pytest.fixture()
def montar(app, monkeypatch):
    """Instala um agente de mentira (e um histórico novo) no app e devolve o provedor falso."""
    def _montar(roteiro, executor=None):
        prov = ProvedorFalso(roteiro)
        monkeypatch.setitem(app.extensions, "agente", Agente(prov, executor=executor or Espiao()))
        monkeypatch.setitem(app.extensions, "historico", Historico())
        return prov
    return _montar


@pytest.fixture()
def http(app):
    auth._falhas.clear()
    with app.test_client() as navegador:
        yield navegador
    auth._falhas.clear()


def logar_como(http, cliente_id):
    """Simula a sessão de login sem passar pela senha."""
    with http.session_transaction() as s:
        s["cliente_id"], s["nome"] = cliente_id, f"Cliente {cliente_id}"


def falar(http, msg="oi", **extra):
    return http.post("/api/chat", json={"message": msg, **extra})


# ================================================================== acesso
def test_sem_login_e_recusado_e_o_agente_nem_roda(http, montar):
    prov = montar([texto("não deveria rodar")])
    assert falar(http).status_code == 401
    assert prov.iniciais == []


def test_sem_agente_configurado_responde_503_claro(app, http, monkeypatch):
    monkeypatch.setitem(app.extensions, "agente", None)
    logar_como(http, 1)
    r = falar(http)
    assert r.status_code == 503 and "configurado" in r.get_json()["error"]


def test_validacao_da_mensagem_vem_antes_do_agente(http, montar):
    prov = montar([texto("x")])
    logar_como(http, 1)
    assert falar(http, "   ").status_code == 400
    assert falar(http, "a" * 1001).status_code == 400
    assert http.post("/api/chat", data="oi").status_code == 415
    assert prov.iniciais == []


# ============================================================ resposta e sessão
def test_resposta_do_agente_volta_no_campo_reply(http, montar):
    montar([texto("Olá, tudo bem?")])
    logar_como(http, 1)
    r = falar(http, "oi")
    assert r.status_code == 200 and r.get_json() == {"reply": "Olá, tudo bem?"}


def test_o_cliente_do_contexto_vem_da_sessao_e_nao_do_corpo(http, montar):
    espiao = Espiao()
    montar([chama(("c", "listar_meus_pets", "{}")), texto("ok")], espiao)
    logar_como(http, 7)
    falar(http, "meus pets", cliente_id=999, clienteId=999)        # tentativa de forjar a identidade
    assert espiao.contextos[0].cliente_id == 7
    assert espiao.contextos[0].conn is not None


def test_a_conexao_e_fechada_depois_de_responder(http, montar, monkeypatch):
    fechadas = []
    class Conn:
        def close(self): fechadas.append(1)
    monkeypatch.setattr(routes, "get_connection", lambda: Conn())
    montar([texto("ok")])
    logar_como(http, 1)
    assert falar(http).status_code == 200 and fechadas == [1]


# ================================================================== histórico
def test_segunda_mensagem_leva_a_primeira_como_historico(http, montar):
    prov = montar([texto("Olá!"), texto("Tem sim.")])
    logar_como(http, 1)
    falar(http, "oi")
    falar(http, "tem racao?")
    assert prov.iniciais[0][:-1] == []                                  # a 1a não tinha histórico
    assert [(m.papel, m.texto) for m in prov.iniciais[1][:-1]] == [("user", "oi"), ("assistant", "Olá!")]
    assert prov.iniciais[1][-1].texto.endswith("tem racao?")


def test_historico_guarda_a_fala_do_cliente_sem_o_bloco_de_contexto(http, montar, app):
    montar([texto("Olá!")])
    logar_como(http, 1)
    falar(http, "oi")
    (conversa,) = app.extensions["historico"]._conversas.values()
    assert conversa[0].texto == "oi"


def test_clientes_diferentes_nao_compartilham_conversa(app, montar):
    prov = montar([texto("a"), texto("b")])
    with app.test_client() as c1, app.test_client() as c2:
        logar_como(c1, 1)
        logar_como(c2, 2)
        falar(c1, "segredo do cliente 1")
        falar(c2, "oi")
    assert prov.iniciais[1][:-1] == []


def test_nova_conversa_zera_o_contexto(http, montar, app):
    prov = montar([texto("1"), texto("2")])
    logar_como(http, 1)
    falar(http, "primeira")
    assert app.extensions["historico"]._conversas                        # havia uma conversa guardada
    assert http.post("/api/chat/nova", json={}).get_json() == {"status": "ok"}
    assert not app.extensions["historico"]._conversas                    # e o servidor a esqueceu
    falar(http, "segunda")
    assert prov.iniciais[1][:-1] == []


def test_nova_conversa_exige_login_e_json(http, montar):
    montar([])
    assert http.post("/api/chat/nova", json={}).status_code == 401
    logar_como(http, 1)
    assert http.post("/api/chat/nova", data="x").status_code == 415
    assert http.post("/api/chat/nova", json={}).status_code == 200      # sem conversa aberta também funciona


def test_logout_e_novo_login_comecam_conversa_nova(http, montar, ctx):
    cur = ctx.conn.cursor()
    cur.execute("SELECT id, email FROM cliente WHERE senha_hash IS NOT NULL ORDER BY id LIMIT 1")
    cid, email = cur.fetchone()
    cur.close()
    prov = montar([texto("1"), texto("2")])
    http.post("/api/login", json={"email": email, "senha": SENHA_DEMO})
    falar(http, "primeira")
    http.post("/api/logout", json={})
    http.post("/api/login", json={"email": email, "senha": SENHA_DEMO})
    falar(http, "segunda")
    assert prov.iniciais[1][:-1] == []


# ========================================================== falhas, sem vazar
def test_erro_do_provedor_vira_503_generico_e_nao_entra_no_historico(http, montar, app):
    prov = montar([ErroProvedor("CREDENCIAL_INVALIDA", "O assistente está indisponível no momento."), texto("ok")])
    logar_como(http, 1)
    r = falar(http, "oi")
    assert r.status_code == 503 and r.get_json() == {"error": "O assistente está indisponível no momento."}
    assert not app.extensions["historico"]._conversas              # a troca que falhou não é lembrada
    assert falar(http, "oi de novo").status_code == 200            # e o chat continua funcionando


def test_banco_fora_do_ar_vira_503_e_o_agente_nem_roda(http, montar, monkeypatch):
    def quebra():
        raise mysql.connector.errors.OperationalError("senha=segredo host=interno")
    monkeypatch.setattr(routes, "get_connection", quebra)
    prov = montar([texto("não deveria rodar")])
    logar_como(http, 1)
    r = falar(http)
    assert r.status_code == 503 and "segredo" not in r.get_data(as_text=True)
    assert prov.iniciais == []


def test_erro_inesperado_vira_500_sem_vazar_detalhe(http, montar):
    montar([RuntimeError("stack trace secreto")])
    logar_como(http, 1)
    r = falar(http)
    assert r.status_code == 500 and "secreto" not in r.get_data(as_text=True)


def test_conexao_fecha_mesmo_quando_o_provedor_falha(http, montar, monkeypatch):
    fechadas = []
    class Conn:
        def close(self): fechadas.append(1)
    monkeypatch.setattr(routes, "get_connection", lambda: Conn())
    montar([ErroProvedor("SEM_CONEXAO", "x")])
    logar_como(http, 1)
    falar(http)
    assert fechadas == [1]