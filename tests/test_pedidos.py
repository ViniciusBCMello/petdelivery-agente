import json
from decimal import Decimal

import pytest

from app.tools import executar


def sql(ctx, consulta, params=()):
    cur = ctx.conn.cursor()
    cur.execute(consulta, params)
    linhas = cur.fetchall()
    cur.close()
    return linhas


def dois_clientes_com_pedidos(ctx):
    r = sql(ctx, "SELECT cliente_id FROM pedido GROUP BY cliente_id ORDER BY COUNT(*) DESC, cliente_id LIMIT 2")
    return r[0][0], r[1][0]


def total_pedido(ctx, pedido_id):
    return sql(ctx, "SELECT COALESCE(SUM(quantidade * preco_unitario), 0) FROM itens_pedido WHERE pedido_id = %s",
               (pedido_id,))[0][0]


# ================================================================ listar_meus_pedidos
def test_lista_exatamente_os_pedidos_do_cliente(ctx, como_cliente):
    a, _ = dois_clientes_com_pedidos(ctx)
    esperado = [r[0] for r in sql(ctx, "SELECT id FROM pedido WHERE cliente_id = %s "
                                       "ORDER BY criado_em DESC, id DESC LIMIT 10", (a,))]
    d = executar("listar_meus_pedidos", {}, como_cliente(a))["dados"]
    assert [p["pedido_id"] for p in d["pedidos"]] == esperado          # so os dele, do mais recente ao mais antigo


def test_total_e_quantidade_de_itens_batem_com_o_banco(ctx, como_cliente):
    a, _ = dois_clientes_com_pedidos(ctx)
    for p in executar("listar_meus_pedidos", {}, como_cliente(a))["dados"]["pedidos"]:
        assert Decimal(p["total"]) == total_pedido(ctx, p["pedido_id"])
        qtd = sql(ctx, "SELECT COALESCE(SUM(quantidade), 0) FROM itens_pedido WHERE pedido_id = %s", (p["pedido_id"],))
        assert p["quantidade_itens"] == qtd[0][0]


def test_filtro_por_status(ctx, como_cliente):
    a, _ = dois_clientes_com_pedidos(ctx)
    todos = executar("listar_meus_pedidos", {}, como_cliente(a))["dados"]["pedidos"]
    status = todos[0]["status"]
    filtrados = executar("listar_meus_pedidos", {"status": status.upper()}, como_cliente(a))["dados"]["pedidos"]
    assert filtrados and all(p["status"] == status for p in filtrados)
    assert len(filtrados) == sum(1 for p in todos if p["status"] == status)


def test_status_invalido_e_rejeitado(como_cliente):
    for status in ("enviado", "", 3):
        r = executar("listar_meus_pedidos", {"status": status}, como_cliente(1))
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", status


def test_cliente_sem_pedidos_recebe_lista_vazia(como_cliente):
    assert executar("listar_meus_pedidos", {}, como_cliente(999999))["dados"]["quantidade"] == 0


# ================================================================== consultar_pedido
def primeiro_pedido(ctx, cliente_id):
    return sql(ctx, "SELECT id FROM pedido WHERE cliente_id = %s AND status <> 'carrinho' "
                    "ORDER BY id LIMIT 1", (cliente_id,))[0][0]


def test_detalhes_do_proprio_pedido(ctx, como_cliente):
    a, _ = dois_clientes_com_pedidos(ctx)
    pid = primeiro_pedido(ctx, a)
    d = executar("consultar_pedido", {"pedido_id": pid}, como_cliente(a))["dados"]
    assert d["pedido_id"] == pid and d["itens"] and Decimal(d["total"]) == total_pedido(ctx, pid)
    assert sum(Decimal(i["subtotal"]) for i in d["itens"]) == Decimal(d["total"])
    assert d["quantidade_itens"] == sum(i["quantidade"] for i in d["itens"])
    tentativas = sql(ctx, "SELECT COUNT(*) FROM pagamento WHERE pedido_id = %s", (pid,))[0][0]
    assert d["pagamento"]["tentativas"] == tentativas


def test_pedido_de_outro_cliente_e_inexistente_para_quem_pergunta(ctx, como_cliente):
    a, b = dois_clientes_com_pedidos(ctx)
    pedido_do_b = primeiro_pedido(ctx, b)
    alheio = executar("consultar_pedido", {"pedido_id": pedido_do_b}, como_cliente(a))
    inexistente = executar("consultar_pedido", {"pedido_id": 9999999}, como_cliente(a))
    assert alheio["ok"] is False and alheio["erro"]["codigo"] == "PEDIDO_NAO_ENCONTRADO"
    assert alheio == inexistente                  # resposta IDENTICA: nao revela que o pedido existe


def test_nenhum_dado_do_dono_vaza_para_outro_cliente(ctx, como_cliente):
    a, b = dois_clientes_com_pedidos(ctx)
    for (pid,) in sql(ctx, "SELECT id FROM pedido WHERE cliente_id = %s", (b,)):
        assert not executar("consultar_pedido", {"pedido_id": pid}, como_cliente(a))["ok"]


def test_codigo_do_gateway_de_pagamento_nunca_aparece(ctx, como_cliente):
    a, _ = dois_clientes_com_pedidos(ctx)
    for (pid,) in sql(ctx, "SELECT id FROM pedido WHERE cliente_id = %s", (a,)):
        texto = json.dumps(executar("consultar_pedido", {"pedido_id": pid}, como_cliente(a)))
        assert "MP-" not in texto


def test_entregador_so_aparece_em_entrega_e_so_com_primeiro_nome_e_placa(ctx, como_cliente):
    pid, cid, nome = sql(ctx, "SELECT p.id, p.cliente_id, e.nome FROM pedido p JOIN entregador e "
                              "ON e.id = p.entregador_id WHERE p.status IN ('em_entrega','entregue') LIMIT 1")[0]
    r = executar("consultar_pedido", {"pedido_id": pid}, como_cliente(cid))
    assert set(r["dados"]["entregador"]) == {"primeiro_nome", "placa_veiculo"}
    assert nome not in json.dumps(r, ensure_ascii=False)        # nome completo nao aparece
    pago = sql(ctx, "SELECT id, cliente_id FROM pedido WHERE status IN ('pago','em_separacao') LIMIT 1")[0]
    assert executar("consultar_pedido", {"pedido_id": pago[0]}, como_cliente(pago[1]))["dados"]["entregador"] is None


def test_entregador_atribuido_nao_aparece_fora_de_entrega(ctx, como_cliente):
    # mesmo que o banco tenha um entregador atribuido, a ferramenta so o mostra em entrega/entregue
    pid, cid = sql(ctx, "SELECT id, cliente_id FROM pedido WHERE status = 'pago' LIMIT 1")[0]
    cur = ctx.conn.cursor()
    try:
        cur.execute("UPDATE pedido SET entregador_id = (SELECT id FROM entregador LIMIT 1) WHERE id = %s", (pid,))
        r = executar("consultar_pedido", {"pedido_id": pid}, como_cliente(cid))
        assert r["ok"] and r["dados"]["entregador"] is None
    finally:
        ctx.conn.rollback()                      # nao deixa nada gravado
        cur.close()


def test_carrinho_nao_tem_pagamento(ctx, como_cliente):
    pid, cid = sql(ctx, "SELECT id, cliente_id FROM pedido WHERE status = 'carrinho' LIMIT 1")[0]
    d = executar("consultar_pedido", {"pedido_id": pid}, como_cliente(cid))["dados"]
    assert d["pagamento"] == {"tentativas": 0, "aprovado": False, "ultima_tentativa": None}
    assert d["loja"] is None and d["codigo"] is None


def test_pedido_id_invalido(como_cliente):
    for valor in ("abc", 0, -1, 1.5, True, None):
        r = executar("consultar_pedido", {"pedido_id": valor}, como_cliente(1))
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", valor