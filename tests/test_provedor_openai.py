"""Adaptador da OpenAI: usa o SDK de verdade, mas a rede é trocada por um transporte falso
(httpx.MockTransport). Assim conferimos o que SERIA enviado e como a resposta é lida,
sem chave, sem internet e sem custo."""
import json
import logging

import httpx
import openai
import pytest

from app.agente.provedor import (ErroProvedor, Mensagem, ProvedorOpenAI, ResultadoFerramenta,
                                 criar_provedor)

CHAVE = "sk-teste-NAO-E-UMA-CHAVE-REAL"
ESPECS = [{"name": "buscar_produtos", "description": "Busca produtos ativos.",
           "parameters": {"type": "object", "properties": {"termo": {"type": "string", "description": "palavras"}},
                          "required": ["termo"], "additionalProperties": False}}]


def corpo(saida, uso=None, status="completed", id="resp_1"):
    return {"id": id, "object": "response", "created_at": 0, "model": "modelo-teste", "status": status,
            "output": saida, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": uso or {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
                             "input_tokens_details": {"cached_tokens": 80},
                             "output_tokens_details": {"reasoning_tokens": 10}}}


def msg(t):
    return {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": t, "annotations": []}]}


def chamada(call_id, nome, args):
    return {"type": "function_call", "id": "fc_" + call_id, "call_id": call_id, "name": nome,
            "arguments": args, "status": "completed"}


def provedor(respostas):
    """Provedor cujo 'servidor' devolve as respostas na ordem. Devolve (provedor, pedidos feitos)."""
    pedidos, fila = [], list(respostas)

    def servidor(req: httpx.Request):
        pedidos.append(req)
        item = fila.pop(0)
        if isinstance(item, Exception):
            raise item
        status, json_ = item if isinstance(item, tuple) else (200, item)
        return httpx.Response(status, json=json_)

    cliente = openai.OpenAI(api_key=CHAVE, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(servidor)))
    return ProvedorOpenAI(CHAVE, "modelo-teste", cliente=cliente), pedidos


def corpo_enviado(req):
    return json.loads(req.content)


# ====================================================== o que é enviado
def test_primeira_chamada_tem_o_formato_esperado():
    prov, pedidos = provedor([corpo([msg("Olá!")])])
    prov.abrir_turno("INSTRUCOES FIXAS", ESPECS).iniciar([Mensagem("user", "oi")])
    req = pedidos[0]
    assert req.method == "POST" and req.url.path.endswith("/responses")
    assert req.headers["authorization"] == f"Bearer {CHAVE}"
    b = corpo_enviado(req)
    assert b["model"] == "modelo-teste" and b["instructions"] == "INSTRUCOES FIXAS"
    assert b["input"] == [{"role": "user", "content": "oi"}]
    assert "previous_response_id" not in b                          # primeira chamada: nada a encadear
    assert b["max_output_tokens"] > 0
    assert b["tools"] == [{"type": "function", "name": "buscar_produtos", "description": "Busca produtos ativos.",
                           "parameters": ESPECS[0]["parameters"], "strict": False}]


def test_historico_vai_como_mensagens_de_usuario_e_assistente():
    prov, pedidos = provedor([corpo([msg("ok")])])
    prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "oi"), Mensagem("assistant", "olá"), Mensagem("user", "tem racao?")])
    assert corpo_enviado(pedidos[0])["input"] == [{"role": "user", "content": "oi"},
                                                  {"role": "assistant", "content": "olá"},
                                                  {"role": "user", "content": "tem racao?"}]


def test_resultado_de_ferramenta_volta_encadeado_ao_pedido_anterior():
    prov, pedidos = provedor([corpo([chamada("call_9", "buscar_produtos", '{"termo":"racao"}')], id="resp_A"),
                              corpo([msg("Temos sim.")], id="resp_B")])
    turno = prov.abrir_turno("INSTR", ESPECS)
    r1 = turno.iniciar([Mensagem("user", "tem racao?")])
    r2 = turno.continuar([ResultadoFerramenta("call_9", '{"ok": true, "dados": {}}')])

    assert [(c.id, c.nome, c.argumentos_json) for c in r1.chamadas] == [("call_9", "buscar_produtos", '{"termo":"racao"}')]
    b2 = corpo_enviado(pedidos[1])
    assert b2["previous_response_id"] == "resp_A"
    assert b2["input"] == [{"type": "function_call_output", "call_id": "call_9", "output": '{"ok": true, "dados": {}}'}]
    assert b2["instructions"] == "INSTR" and b2["tools"][0]["name"] == "buscar_produtos"   # reenviados
    assert r2.texto == "Temos sim." and r2.chamadas == ()


def test_varias_chamadas_paralelas_sao_lidas_e_respondidas_juntas():
    prov, pedidos = provedor([corpo([chamada("a", "buscar_produtos", "{}"), chamada("b", "buscar_produtos", "{}")]),
                              corpo([msg("ok")])])
    turno = prov.abrir_turno("i", ESPECS)
    r1 = turno.iniciar([Mensagem("user", "x")])
    assert [c.id for c in r1.chamadas] == ["a", "b"]
    turno.continuar([ResultadoFerramenta("a", "1"), ResultadoFerramenta("b", "2")])
    assert [i["call_id"] for i in corpo_enviado(pedidos[1])["input"]] == ["a", "b"]


def test_cada_turno_comeca_do_zero_sem_herdar_o_encadeamento():
    prov, pedidos = provedor([corpo([msg("1")], id="resp_A"), corpo([msg("2")], id="resp_B")])
    prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "x")])
    prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "y")])
    assert "previous_response_id" not in corpo_enviado(pedidos[1])


# ====================================================== o que é lido
def test_texto_e_uso_sao_lidos():
    prov, _ = provedor([corpo([msg("Olá! Sou o Peteco.")])])
    r = prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "oi")])
    assert r.texto == "Olá! Sou o Peteco." and r.chamadas == ()
    assert (r.uso.entrada, r.uso.saida, r.uso.em_cache, r.uso.raciocinio, r.uso.chamadas) == (120, 30, 80, 10, 1)


def test_resposta_sem_uso_nao_quebra():
    b = corpo([msg("ok")])
    b.pop("usage")
    prov, _ = provedor([b])
    r = prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "oi")])
    assert r.uso.entrada == 0 and r.uso.chamadas == 1


def test_itens_de_raciocinio_na_saida_sao_ignorados():
    raciocinio = {"type": "reasoning", "id": "rs_1", "summary": []}
    prov, _ = provedor([corpo([raciocinio, chamada("c", "buscar_produtos", "{}")])])
    r = prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "x")])
    assert [c.nome for c in r.chamadas] == ["buscar_produtos"]


def test_resposta_incompleta_sem_texto_e_erro():
    b = corpo([], status="incomplete")
    b["incomplete_details"] = {"reason": "max_output_tokens"}
    prov, _ = provedor([b])
    with pytest.raises(ErroProvedor) as e:
        prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "x")])
    assert e.value.codigo == "RESPOSTA_INCOMPLETA"


# ====================================================== falhas do provedor
def erro_http(status, code=None):
    return (status, {"error": {"message": "detalhe tecnico interno", "type": "x", "code": code}})


@pytest.mark.parametrize("resposta, codigo", [
    (erro_http(401, "invalid_api_key"), "CREDENCIAL_INVALIDA"),
    (erro_http(403), "CREDENCIAL_INVALIDA"),
    (erro_http(429, "insufficient_quota"), "SEM_CREDITO"),
    (erro_http(429, "rate_limit_exceeded"), "LIMITE_DE_USO"),
    (erro_http(400), "REQUISICAO_INVALIDA"),
    (erro_http(404), "MODELO_NAO_ENCONTRADO"),
    (erro_http(500), "PROVEDOR_INDISPONIVEL"),
    (erro_http(503), "PROVEDOR_INDISPONIVEL"),
    (httpx.ReadTimeout("demorou"), "TEMPO_ESGOTADO"),
    (httpx.ConnectError("sem rede"), "SEM_CONEXAO"),
])
def test_falhas_viram_erro_provedor_com_mensagem_segura(resposta, codigo):
    prov, _ = provedor([resposta])
    with pytest.raises(ErroProvedor) as e:
        prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "x")])
    assert e.value.codigo == codigo
    assert "detalhe" not in e.value.mensagem_usuario and "sem rede" not in e.value.mensagem_usuario
    assert CHAVE not in e.value.mensagem_usuario


def test_logs_de_falha_ajudam_a_depurar_sem_vazar_dados_do_cliente(caplog):
    prov, _ = provedor([erro_http(404, "model_not_found")])
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ErroProvedor):
            prov.abrir_turno("PROMPT SECRETO DO SISTEMA", ESPECS).iniciar([Mensagem("user", "meu cpf e 123")])
    tudo = caplog.text
    assert "MODELO_NAO_ENCONTRADO" in tudo and "detalhe tecnico interno" in tudo      # a mensagem do provedor aparece
    assert CHAVE not in tudo and "PROMPT SECRETO" not in tudo and "meu cpf" not in tudo


def test_erro_de_credencial_nao_registra_nem_a_mensagem_do_provedor(caplog):
    prov, _ = provedor([erro_http(401, "invalid_api_key")])
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ErroProvedor):
            prov.abrir_turno("i", ESPECS).iniciar([Mensagem("user", "x")])
    assert "CREDENCIAL_INVALIDA" in caplog.text
    assert "detalhe tecnico interno" not in caplog.text and CHAVE not in caplog.text


# ====================================================== montagem
def test_criar_provedor_exige_chave_e_modelo():
    base = {"LLM_API_KEY": "k", "LLM_MODEL": "m", "LLM_TIMEOUT": 5.0}
    assert criar_provedor({**base, "LLM_API_KEY": ""}) is None
    assert criar_provedor({**base, "LLM_MODEL": ""}) is None
    assert isinstance(criar_provedor(base), ProvedorOpenAI)