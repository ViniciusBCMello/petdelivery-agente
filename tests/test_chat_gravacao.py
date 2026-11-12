"""Gravação pelo chat, de ponta a ponta na rota: o cliente vê o resumo numa requisição e confirma na
SEGUINTE. Usa ferramentas reais e o banco (desfeito no fim); só o LLM é de mentira."""
import json

import pytest
from test_falsos import ProvedorFalso, chama, texto

from app import routes
from app.agente.historico import Historico
from app.agente.orquestrador import Agente
from test_agendar import donos, livre, pedido, vets


@pytest.fixture()
def cenario(app, escrita, monkeypatch):
    cli, pet = donos(escrita)[0]
    vet = vets(escrita)["clínica geral"]
    hora = livre(escrita, vet)
    monkeypatch.setattr(routes, "get_connection", lambda: escrita.conn)
    monkeypatch.setitem(app.extensions, "confirmacoes", escrita.cofre)
    monkeypatch.setitem(app.extensions, "historico", Historico())

    def instalar(roteiro):
        prov = ProvedorFalso(roteiro)
        monkeypatch.setitem(app.extensions, "agente", Agente(prov))
        return prov

    def entrar(http, cliente_id):
        with http.session_transaction() as s:
            s["cliente_id"], s["nome"] = cliente_id, f"Cliente {cliente_id}"

    def falar(http, msg):
        return http.post("/api/chat", json={"message": msg})

    args = pedido(pet, vet, hora)
    contar = lambda: escrita.sql("SELECT COUNT(*) FROM agendamento")[0][0]
    return type("Cenario", (), dict(env=escrita, cli=cli, pet=pet, vet=vet, hora=hora, args=args, instalar=instalar,
                                    entrar=entrar, falar=falar, contar=staticmethod(contar), cli2=donos(escrita)[1][0]))


def codigo_recebido(prov, indice=0):
    return json.loads(prov.envios[indice][0].conteudo)["dados"]["codigo_confirmacao"]


def confirma_com_o_codigo(prov, args, indice=0):
    return chama(("c2", "agendar", json.dumps({**args, "confirmacao": codigo_recebido(prov, indice)})))


def test_resumo_numa_requisicao_e_gravacao_na_seguinte(app, cenario):
    c = cenario
    prov = c.instalar([chama(("c1", "agendar", json.dumps(c.args))), texto("Confirma o agendamento?"),
                       lambda p: confirma_com_o_codigo(p, c.args), texto("Agendado!")])
    antes = c.contar()
    with app.test_client() as http:
        c.entrar(http, c.cli)
        assert c.falar(http, "quero marcar uma consulta").get_json()["reply"] == "Confirma o agendamento?"
        assert c.contar() == antes                                  # 1ª requisição: nada gravado
        assert c.falar(http, "sim, pode marcar").get_json()["reply"] == "Agendado!"
    assert c.contar() == antes + 1                                  # 2ª requisição: gravou
    final = json.loads(prov.envios[1][0].conteudo)["dados"]
    assert final["gravado"] is True and final["status"] == "agendado"


def test_modelo_nao_consegue_confirmar_na_mesma_mensagem(app, cenario):
    c = cenario
    prov = c.instalar([chama(("c1", "agendar", json.dumps(c.args))),
                       lambda p: confirma_com_o_codigo(p, c.args),          # tenta confirmar sem ouvir o cliente
                       texto("Preciso da sua confirmação.")])
    antes = c.contar()
    with app.test_client() as http:
        c.entrar(http, c.cli)
        assert c.falar(http, "quero marcar uma consulta").status_code == 200
    assert c.contar() == antes
    assert json.loads(prov.envios[1][0].conteudo)["erro"]["codigo"] == "CONFIRMACAO_PREMATURA"


def test_codigo_nao_serve_para_outro_cliente(app, cenario):
    c = cenario
    prov = c.instalar([chama(("c1", "agendar", json.dumps(c.args))), texto("Confirma?"),
                       lambda p: confirma_com_o_codigo(p, c.args), texto("não deu")])
    antes = c.contar()
    with app.test_client() as dono, app.test_client() as intruso:
        c.entrar(dono, c.cli)
        c.entrar(intruso, c.cli2)
        c.falar(dono, "quero marcar")
        c.falar(intruso, "sim")                                     # outro cliente tenta usar o código
    assert c.contar() == antes
    assert json.loads(prov.envios[1][0].conteudo)["erro"]["codigo"] in ("CONFIRMACAO_INVALIDA", "PET_NAO_ENCONTRADO")


def test_cancelamento_pelo_chat_em_duas_requisicoes(app, cenario):
    c = cenario
    # primeiro cria o agendamento direto, para ter o que cancelar
    from app.tools import executar
    ctx = c.env.como(c.cli, turno=1)
    cod = executar("agendar", c.args, ctx)["dados"]["codigo_confirmacao"]
    ag = executar("agendar", {**c.args, "confirmacao": cod}, c.env.como(c.cli, turno=2))["dados"]["agendamento_id"]
    prov = c.instalar([chama(("c1", "cancelar_agendamento", json.dumps({"agendamento_id": ag}))), texto("Confirma o cancelamento?"),
                       lambda p: chama(("c2", "cancelar_agendamento",
                                        json.dumps({"agendamento_id": ag, "confirmacao": codigo_recebido(p)}))),
                       texto("Cancelado.")])
    with app.test_client() as http:
        c.entrar(http, c.cli)
        c.falar(http, "cancela minha consulta")
        assert c.env.sql("SELECT status FROM agendamento WHERE id = %s", (ag,))[0][0] == "agendado"
        c.falar(http, "sim")
    assert c.env.sql("SELECT status FROM agendamento WHERE id = %s", (ag,))[0][0] == "cancelado"