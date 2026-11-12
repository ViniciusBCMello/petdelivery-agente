"""Vendas pelo chat, de ponta a ponta na rota: o cliente vê o resumo numa requisição e confirma na SEGUINTE.
Ferramentas reais e banco (desfeito no fim); só o LLM é de mentira."""
import json

import pytest
from falsos import ProvedorFalso, chama, texto

from app import routes
from app.agente.historico import Historico
from app.agente.orquestrador import Agente
from test_vendas import add, carrinhos, estoque, pedido, v  # noqa: F401  (v é a fixture de dados)


@pytest.fixture()
def chat(app, v, monkeypatch):  # noqa: F811
    monkeypatch.setattr(routes, "get_connection", lambda: v.env.conn)
    monkeypatch.setitem(app.extensions, "confirmacoes", v.env.cofre)
    monkeypatch.setitem(app.extensions, "historico", Historico())

    def instalar(roteiro):
        prov = ProvedorFalso(roteiro)
        monkeypatch.setitem(app.extensions, "agente", Agente(prov))
        return prov

    def navegador(cliente_id):
        http = app.test_client()
        with http.session_transaction() as s:
            s["cliente_id"], s["nome"] = cliente_id, f"Cliente {cliente_id}"
        return http

    def falar(http, msg):
        return http.post("/api/chat", json={"message": msg})

    return type("Chat", (), dict(instalar=staticmethod(instalar), navegador=staticmethod(navegador), falar=staticmethod(falar)))


def corpo_adicionar(item, qtd):
    d = {"produto_id": item.produto_id, "loja_id": item.loja_id, "quantidade": qtd}
    if item.cor:
        d["cor"] = item.cor
    if item.tamanho:
        d["tamanho"] = item.tamanho
    return json.dumps(d)


def resultado(prov, lote, posicao=0):
    return json.loads(prov.envios[lote][posicao].conteudo)


def com_codigo(prov, args, lote):
    """Chamada de confirmação usando o código que o servidor entregou ao modelo num resultado anterior."""
    codigo = resultado(prov, lote)["dados"]["codigo_confirmacao"]
    return chama(("cf", "finalizar_pedido", json.dumps({**args, "confirmacao": codigo})))


def test_compra_inteira_em_duas_mensagens(app, v, chat):  # noqa: F811
    fin = {"endereco_id": v.end}
    prov = chat.instalar([
        chama(("c1", "adicionar_ao_carrinho", corpo_adicionar(v.a, 2))),     # carrinho: sem confirmação
        chama(("c2", "finalizar_pedido", json.dumps(fin))),                  # etapa 1: só o resumo
        texto("Seu carrinho tem 2 itens. Confirma o pedido?"),
        lambda p: com_codigo(p, fin, lote=1),                                # etapa 2, na mensagem seguinte
        texto("Pedido feito! Segue o link de pagamento (ilustrativo)."),
    ])
    with chat.navegador(v.cli) as http:
        assert chat.falar(http, "quero 2 desse produto").get_json()["reply"].startswith("Seu carrinho")
        (pid, _), = carrinhos(v.env, v.cli)
        assert pedido(v.env, pid)[0] == "carrinho" and estoque(v.env, v.a) == v.a.estoque       # nada foi vendido ainda
        assert chat.falar(http, "sim, confirmo").get_json()["reply"].startswith("Pedido feito")
    assert pedido(v.env, pid)[0] == "aguardando_pagamento" and estoque(v.env, v.a) == v.a.estoque - 2
    final = resultado(prov, 2)["dados"]
    assert final["gravado"] is True and final["pagamento"]["ilustrativo"] is True


def test_modelo_nao_consegue_finalizar_na_mesma_mensagem(app, v, chat):  # noqa: F811
    fin = {"endereco_id": v.end}
    prov = chat.instalar([
        chama(("c1", "adicionar_ao_carrinho", corpo_adicionar(v.a, 1))),
        chama(("c2", "finalizar_pedido", json.dumps(fin))),
        lambda p: com_codigo(p, fin, lote=1),                                # tenta confirmar sem ouvir o cliente
        texto("Preciso da sua confirmação."),
    ])
    with chat.navegador(v.cli) as http:
        assert chat.falar(http, "quero comprar").status_code == 200
    assert resultado(prov, 2)["erro"]["codigo"] == "CONFIRMACAO_PREMATURA"
    (pid, _), = carrinhos(v.env, v.cli)
    assert pedido(v.env, pid)[0] == "carrinho" and estoque(v.env, v.a) == v.a.estoque


def test_cancelamento_pelo_chat_devolve_o_estoque(app, v, chat):  # noqa: F811
    from test_vendas import pedido_aguardando
    pid = pedido_aguardando(v, (v.a, 2))
    prov = chat.instalar([
        chama(("c1", "cancelar_pedido", json.dumps({"pedido_id": pid}))), texto("Confirma o cancelamento?"),
        lambda p: chama(("c2", "cancelar_pedido", json.dumps(
            {"pedido_id": pid, "confirmacao": resultado(p, 0)["dados"]["codigo_confirmacao"]}))),
        texto("Cancelado."),
    ])
    with chat.navegador(v.cli) as http:
        chat.falar(http, "cancela meu pedido")
        assert pedido(v.env, pid)[0] == "aguardando_pagamento"
        chat.falar(http, "sim")
    assert pedido(v.env, pid)[0] == "cancelado" and estoque(v.env, v.a) == v.a.estoque


def test_o_cliente_do_carrinho_vem_da_sessao(app, v, chat):  # noqa: F811
    chat.instalar([chama(("c1", "adicionar_ao_carrinho", json.dumps(
        {"produto_id": v.a.produto_id, "loja_id": v.a.loja_id, "quantidade": 1, "cliente_id": v.cli2,
         **({"cor": v.a.cor} if v.a.cor else {}), **({"tamanho": v.a.tamanho} if v.a.tamanho else {})}))),
        texto("não deu")])
    with chat.navegador(v.cli) as http:
        chat.falar(http, "coloca no carrinho do outro cliente")
    assert carrinhos(v.env, v.cli) == [] and carrinhos(v.env, v.cli2) == []      # o argumento forjado foi recusado