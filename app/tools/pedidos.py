"""Ferramentas de PEDIDOS do cliente logado: listar_meus_pedidos e consultar_pedido.

Como em cliente.py, o cliente vem de ctx.cliente_id, nunca de um parametro.
"""
from decimal import Decimal

from .base import ErroFerramenta, dinheiro, exigir_cliente, exigir_inteiro, exigir_texto, ferramenta

MAX_PEDIDOS = 10
STATUS_PEDIDO = ("carrinho", "aguardando_pagamento", "pago", "em_separacao", "em_entrega", "entregue", "cancelado")


def _data_hora(valor):
    return None if valor is None else valor.strftime("%Y-%m-%d %H:%M")


@ferramenta(
    nome="listar_meus_pedidos",
    descricao=(
        "Lista os pedidos mais recentes do cliente logado (ate 10), com codigo, situacao, loja, "
        "quantidade de itens e total. Pode filtrar pela situacao: carrinho, aguardando_pagamento, pago, "
        "em_separacao, em_entrega, entregue ou cancelado. Use consultar_pedido para ver os detalhes."
    ),
    parametros={
        "status": {"tipo": "string", "obrigatorio": False,
                   "descricao": "Opcional. Situacao do pedido, por exemplo 'em_entrega'."},
    },
)
def listar_meus_pedidos(ctx, status=None):
    cliente_id = exigir_cliente(ctx)
    filtro, params = "", [cliente_id]
    if status is not None:
        status = exigir_texto(status, "status", max_len=30).lower()
        if status not in STATUS_PEDIDO:
            raise ErroFerramenta("PARAMETRO_INVALIDO", f"'status' deve ser um destes: {', '.join(STATUS_PEDIDO)}.")
        filtro = " AND p.status = %s"
        params.append(status)

    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT p.id, p.codigo_transacao, p.status, p.criado_em, p.data_finalizacao, "
            "l.nome_fantasia AS loja, COALESCE(SUM(i.quantidade), 0) AS qtd_itens, "
            "COALESCE(SUM(i.quantidade * i.preco_unitario), 0) AS total "
            "FROM pedido p LEFT JOIN loja l ON l.id = p.loja_id "
            "LEFT JOIN itens_pedido i ON i.pedido_id = p.id "
            f"WHERE p.cliente_id = %s{filtro} "
            "GROUP BY p.id, p.codigo_transacao, p.status, p.criado_em, p.data_finalizacao, l.nome_fantasia "
            "ORDER BY p.criado_em DESC, p.id DESC LIMIT %s", params + [MAX_PEDIDOS + 1])
        linhas = cur.fetchall()
    finally:
        cur.close()
    ha_mais = len(linhas) > MAX_PEDIDOS
    linhas = linhas[:MAX_PEDIDOS]
    return {
        "quantidade": len(linhas), "ha_mais_resultados": ha_mais,
        "pedidos": [{"pedido_id": l["id"], "codigo": l["codigo_transacao"], "status": l["status"],
                     "criado_em": _data_hora(l["criado_em"]), "loja": l["loja"],
                     "quantidade_itens": int(l["qtd_itens"]), "total": dinheiro(Decimal(l["total"]))}
                    for l in linhas],
    }


@ferramenta(
    nome="consultar_pedido",
    descricao=(
        "Mostra os detalhes de UM pedido do cliente logado: itens, total, situacao, loja, endereco de "
        "entrega, entregador (so em entrega ou entregue) e resumo do pagamento. "
        "Obtenha o pedido_id em listar_meus_pedidos."
    ),
    parametros={
        "pedido_id": {"tipo": "integer", "obrigatorio": True,
                      "descricao": "Identificador do pedido, obtido em listar_meus_pedidos."},
    },
)
def consultar_pedido(ctx, pedido_id):
    cliente_id = exigir_cliente(ctx)
    pedido_id = exigir_inteiro(pedido_id, "pedido_id")

    cur = ctx.conn.cursor(dictionary=True)
    try:
        # O filtro por cliente_id e o que impede ver o pedido de outra pessoa.
        cur.execute(
            "SELECT p.id, p.codigo_transacao, p.status, p.criado_em, p.data_finalizacao, p.endereco_entrega, "
            "l.id AS loja_id, l.nome_fantasia AS loja, l.bairro AS loja_bairro, "
            "e.nome AS entregador, e.placa_veiculo "
            "FROM pedido p LEFT JOIN loja l ON l.id = p.loja_id "
            "LEFT JOIN entregador e ON e.id = p.entregador_id "
            "WHERE p.id = %s AND p.cliente_id = %s", (pedido_id, cliente_id))
        p = cur.fetchone()
        if p is None:
            # MESMA resposta para "nao existe" e "e de outra pessoa": nao revela quais ids existem.
            raise ErroFerramenta("PEDIDO_NAO_ENCONTRADO", "Nao encontrei esse pedido na sua conta.")
        cur.execute(
            "SELECT pr.nome, ie.cor, ie.tamanho, i.quantidade, i.preco_unitario FROM itens_pedido i "
            "JOIN item_estoque ie ON ie.id = i.item_estoque_id JOIN produto pr ON pr.id = ie.produto_id "
            "WHERE i.pedido_id = %s ORDER BY pr.nome, ie.cor, ie.tamanho", (pedido_id,))
        itens = cur.fetchall()
        cur.execute("SELECT aprovado, criado_em FROM pagamento WHERE pedido_id = %s "
                    "ORDER BY criado_em, id", (pedido_id,))
        pagamentos = cur.fetchall()
    finally:
        cur.close()

    total = sum((Decimal(i["preco_unitario"]) * i["quantidade"] for i in itens), Decimal("0"))
    em_rota = p["status"] in ("em_entrega", "entregue")
    return {
        "pedido_id": p["id"], "codigo": p["codigo_transacao"], "status": p["status"],
        "criado_em": _data_hora(p["criado_em"]), "finalizado_em": _data_hora(p["data_finalizacao"]),
        "endereco_entrega": p["endereco_entrega"],
        "loja": None if p["loja_id"] is None else {"loja_id": p["loja_id"], "loja": p["loja"],
                                                   "bairro": p["loja_bairro"]},
        # So o primeiro nome e a placa: o suficiente para o cliente reconhecer o entregador.
        "entregador": ({"primeiro_nome": p["entregador"].split()[0], "placa_veiculo": p["placa_veiculo"]}
                       if em_rota and p["entregador"] else None),
        "itens": [{"produto": i["nome"], "cor": i["cor"], "tamanho": i["tamanho"], "quantidade": i["quantidade"],
                   "preco_unitario": dinheiro(Decimal(i["preco_unitario"])),
                   "subtotal": dinheiro(Decimal(i["preco_unitario"]) * i["quantidade"])} for i in itens],
        "quantidade_itens": sum(i["quantidade"] for i in itens),
        "total": dinheiro(total),
        # Nada do codigo interno do gateway de pagamento: so o resumo.
        "pagamento": {"tentativas": len(pagamentos), "aprovado": any(g["aprovado"] for g in pagamentos),
                      "ultima_tentativa": _data_hora(pagamentos[-1]["criado_em"]) if pagamentos else None},
    }