"""Ponta a ponta, sem internet: Flask -> agente -> SDK da OpenAI (HTTP simulado) -> ferramentas -> MySQL.

Só o 'servidor da OpenAI' é de mentira. Ele se comporta como um modelo simples: na primeira chamada
pede buscar_produtos; ao receber o resultado, responde citando o primeiro produto encontrado."""
import json

import httpx
import openai
import pytest

from app.agente.historico import Historico
from app.agente.orquestrador import Agente
from app.agente.provedor import ProvedorOpenAI
from test_provedor_openai import chamada, corpo, msg


@pytest.fixture()
def openai_de_mentira(app, monkeypatch):
    pedidos = []

    def servidor(req: httpx.Request):
        b = json.loads(req.content)
        pedidos.append(b)
        saidas = [i for i in b["input"] if i.get("type") == "function_call_output"]
        if not saidas:
            return httpx.Response(200, json=corpo([chamada("call_1", "buscar_produtos", '{"termo": "racao"}')], id="resp_1"))
        resultado = json.loads(saidas[0]["output"])
        primeiro = resultado["dados"]["produtos"][0]["nome"]
        return httpx.Response(200, json=corpo([msg(f"Encontrei: {primeiro}")], id="resp_2"))

    cliente = openai.OpenAI(api_key="k", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(servidor)))
    agente = Agente(ProvedorOpenAI("k", "modelo-teste", cliente=cliente))
    monkeypatch.setitem(app.extensions, "agente", agente)
    monkeypatch.setitem(app.extensions, "historico", Historico())
    return pedidos


def test_do_navegador_ao_banco_e_de_volta(app, openai_de_mentira):
    with app.test_client() as http:
        with http.session_transaction() as s:
            s["cliente_id"], s["nome"] = 1, "Cliente 1"
        r = http.post("/api/chat", json={"message": "tem ração?"})

    assert r.status_code == 200 and r.get_json()["reply"].startswith("Encontrei: ")
    primeira, segunda = openai_de_mentira
    assert primeira["input"][-1]["content"].endswith("tem ração?")
    assert "previous_response_id" not in primeira
    assert segunda["previous_response_id"] == "resp_1"                  # encadeou o resultado da ferramenta
    assert segunda["input"][0]["type"] == "function_call_output"
    assert json.loads(segunda["input"][0]["output"])["ok"] is True      # dados reais do MySQL
    assert {t["name"] for t in primeira["tools"]} >= {"buscar_produtos", "consultar_pedido"}
    assert "cliente_id" not in json.dumps(primeira["tools"])           # nenhuma ferramenta expõe o parâmetro