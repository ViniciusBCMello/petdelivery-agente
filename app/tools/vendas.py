"""
Ferramentas que GRAVAM vendas: adicionar_ao_carrinho, alterar_item_carrinho, finalizar_pedido e cancelar_pedido.

Regras:
  - o cliente vem da sessão (nunca é argumento) e só mexe no PRÓPRIO carrinho e nos PRÓPRIOS pedidos;
  - um pedido é de UMA loja só: o carrinho fica preso à loja do primeiro item;
  - o carrinho aceita só o que há em estoque (soma das linhas <= estoque da variação na loja);
  - o estoque é abatido em finalizar_pedido e devolvido em cancelar_pedido (pedido aguardando pagamento);
  - o agente NUNCA marca um pedido como pago: ele para em 'aguardando_pagamento' e entrega um link ILUSTRATIVO;
  - finalizar_pedido e cancelar_pedido usam a confirmação em duas etapas (confirmacao.py);
  - o banco é a última linha de defesa: estoque nunca negativo (UNSIGNED), quantidade > 0 (CHECK) e
    um item só aparece uma vez por pedido (chave única).
"""
from decimal import Decimal

from . import agenda
from .base import ErroFerramenta, dinheiro, exigir_cliente, exigir_inteiro, exigir_texto, ferramenta
from .confirmacao import conferir, propor

MAX_QTD_ITEM = 50
STATUS_CANCELAVEIS = ("carrinho", "aguardando_pagamento")
LINK_PAGAMENTO = "https://pagamento.petdelivery.example/pedido/{codigo}"      # fictício: ".example" não existe


# ---------------------------------------------------------------------------
# apoio
# ---------------------------------------------------------------------------
def _consulta(ctx, sql, params=(), um=False):
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone() if um else cur.fetchall()
    finally:
        cur.close()


def _opcional(valor, nome):
    """cor/tamanho: texto opcional; vazio vale como 'não informado'."""
    if valor is None:
        return None
    texto = exigir_texto(valor, nome, max_len=100)
    return texto


def _quantidade(valor, minimo=1):
    q = exigir_inteiro(valor, "quantidade", minimo)
    if q > MAX_QTD_ITEM:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'quantidade' deve ser no máximo {MAX_QTD_ITEM} por item.")
    return q


def _carrinho_atual(ctx, cliente_id):
    """O carrinho MAIS RECENTE do cliente (há clientes com mais de um carrinho nos dados)."""
    return _consulta(ctx, "SELECT id, loja_id FROM pedido WHERE cliente_id = %s AND status = 'carrinho' "
                          "ORDER BY id DESC LIMIT 1", (cliente_id,), um=True)


def _linhas(ctx, pedido_id):
    return _consulta(
        ctx,
        "SELECT ip.id AS linha_id, ip.quantidade, ie.id AS item_estoque_id, ie.loja_id, ie.quantidade AS estoque, "
        "ie.cor, ie.tamanho, p.id AS produto_id, p.nome, p.preco, p.ativo "
        "FROM itens_pedido ip JOIN item_estoque ie ON ie.id = ip.item_estoque_id "
        "JOIN produto p ON p.id = ie.produto_id WHERE ip.pedido_id = %s ORDER BY ip.id", (pedido_id,))


def _resumo_linhas(linhas):
    itens, total = [], Decimal("0")
    for l in linhas:
        subtotal = l["preco"] * l["quantidade"]
        total += subtotal
        itens.append({"produto_id": l["produto_id"], "nome": l["nome"], "cor": l["cor"] or None,
                      "tamanho": l["tamanho"] or None, "quantidade": l["quantidade"],
                      "preco_unitario": dinheiro(l["preco"]), "subtotal": dinheiro(subtotal)})
    return itens, total


def _nome_loja(ctx, loja_id):
    if loja_id is None:
        return None
    linha = _consulta(ctx, "SELECT nome_fantasia FROM loja WHERE id = %s", (loja_id,), um=True)
    return linha["nome_fantasia"] if linha else None


def _reprecificar(ctx, cur, pedido_id):
    """Põe nas linhas o preço ATUAL do produto (o carrinho sempre mostra o preço de hoje)."""
    cur.execute("UPDATE itens_pedido ip JOIN item_estoque ie ON ie.id = ip.item_estoque_id "
                "JOIN produto p ON p.id = ie.produto_id SET ip.preco_unitario = p.preco WHERE ip.pedido_id = %s",
                (pedido_id,))


def _variacao(l):
    return {"cor": l["cor"] or None, "tamanho": l["tamanho"] or None}


def _bate(valor_banco, pedido):
    return pedido is None or (valor_banco or "").casefold() == pedido.strip().casefold()


def _situacao_do_carrinho(ctx, pedido_id):
    linhas = _linhas(ctx, pedido_id)
    itens, total = _resumo_linhas(linhas)
    loja = _nome_loja(ctx, linhas[0]["loja_id"]) if linhas else None
    return {"pedido_id": pedido_id, "loja": loja, "itens": itens, "total": dinheiro(total)}


# ---------------------------------------------------------------------------
# adicionar_ao_carrinho
# ---------------------------------------------------------------------------
@ferramenta(
    nome="adicionar_ao_carrinho",
    descricao=(
        "Põe um produto no carrinho do cliente logado (cria o carrinho se não existir). O carrinho é de UMA loja só: "
        "o cliente precisa escolher a loja. Se o produto tem variações (cor/tamanho), informe cor e/ou tamanho; sem "
        "isso a ferramenta lista as opções. Soma à quantidade que já estiver no carrinho. Só aceita o que há em "
        "estoque na loja. Não pede confirmação: é reversível (alterar_item_carrinho). Descubra o produto com "
        "buscar_produtos e a disponibilidade com consultar_estoque."
    ),
    parametros={
        "produto_id": {"tipo": "integer", "obrigatorio": True, "descricao": "Id do produto (buscar_produtos)."},
        "loja_id": {"tipo": "integer", "obrigatorio": True, "descricao": "Id da loja que vai atender o pedido."},
        "quantidade": {"tipo": "integer", "obrigatorio": True,
                       "descricao": f"Quantas unidades acrescentar (1 a {MAX_QTD_ITEM})."},
        "cor": {"tipo": "string", "obrigatorio": False, "descricao": "Opcional. Cor da variação, se o produto tiver."},
        "tamanho": {"tipo": "string", "obrigatorio": False,
                    "descricao": "Opcional. Tamanho da variação, se o produto tiver."},
    },
)
def adicionar_ao_carrinho(ctx, produto_id, loja_id, quantidade, cor=None, tamanho=None):
    cliente_id = exigir_cliente(ctx)
    produto_id = exigir_inteiro(produto_id, "produto_id")
    loja_id = exigir_inteiro(loja_id, "loja_id")
    quantidade = _quantidade(quantidade)
    cor, tamanho = _opcional(cor, "cor"), _opcional(tamanho, "tamanho")

    produto = _consulta(ctx, "SELECT id, nome, preco, ativo FROM produto WHERE id = %s", (produto_id,), um=True)
    if produto is None:
        raise ErroFerramenta("PRODUTO_NAO_ENCONTRADO", f"Não existe produto com id {produto_id}.")
    if not produto["ativo"]:
        raise ErroFerramenta("PRODUTO_INDISPONIVEL", f"O produto '{produto['nome']}' não está mais à venda.")
    loja = _consulta(ctx, "SELECT id, nome_fantasia FROM loja WHERE id = %s", (loja_id,), um=True)
    if loja is None:
        raise ErroFerramenta("LOJA_NAO_ENCONTRADA", f"Não existe loja com id {loja_id}.")

    variacoes = _consulta(ctx, "SELECT id, cor, tamanho, quantidade FROM item_estoque "
                               "WHERE produto_id = %s AND loja_id = %s ORDER BY id", (produto_id, loja_id))
    if not variacoes:
        raise ErroFerramenta("PRODUTO_NAO_VENDIDO_NA_LOJA", f"A loja {loja['nome_fantasia']} não trabalha com '{produto['nome']}'.")
    candidatas = [v for v in variacoes if _bate(v["cor"], cor) and _bate(v["tamanho"], tamanho)]
    opcoes = [{**_variacao(v), "em_estoque": v["quantidade"]} for v in (candidatas or variacoes)]
    if not candidatas:
        raise ErroFerramenta("VARIACAO_NAO_ENCONTRADA",
                             f"Essa cor/tamanho não existe para '{produto['nome']}' nessa loja. Opções: {opcoes}")
    if len(candidatas) > 1:
        raise ErroFerramenta("VARIACAO_OBRIGATORIA",
                             f"'{produto['nome']}' tem variações: informe cor e/ou tamanho. Opções: {opcoes}")
    escolhida = candidatas[0]

    carrinho = _carrinho_atual(ctx, cliente_id)
    linhas = _linhas(ctx, carrinho["id"]) if carrinho else []
    if linhas and {l["loja_id"] for l in linhas} != {loja_id}:
        raise ErroFerramenta(
            "LOJA_DIFERENTE_DO_CARRINHO",
            f"O carrinho já tem itens de {_nome_loja(ctx, linhas[0]['loja_id'])}. Um pedido é de uma loja só: "
            "finalize esse pedido, remova os itens (alterar_item_carrinho com quantidade 0) ou cancele-o "
            "(cancelar_pedido) antes de comprar em outra loja.")

    ja_no_carrinho = next((l for l in linhas if l["item_estoque_id"] == escolhida["id"]), None)
    nova = quantidade + (ja_no_carrinho["quantidade"] if ja_no_carrinho else 0)
    if nova > MAX_QTD_ITEM:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"O máximo é {MAX_QTD_ITEM} unidades por item no carrinho.")
    if nova > escolhida["quantidade"]:
        raise ErroFerramenta(
            "ESTOQUE_INSUFICIENTE",
            f"Só há {escolhida['quantidade']} unidade(s) de '{produto['nome']}' em {loja['nome_fantasia']}"
            + (f" e {ja_no_carrinho['quantidade']} já estão no carrinho." if ja_no_carrinho else "."))

    cur = ctx.conn.cursor()
    try:
        if carrinho is None:
            cur.execute("INSERT INTO pedido (cliente_id, loja_id, status) VALUES (%s, %s, 'carrinho')", (cliente_id, loja_id))
            pedido_id = cur.lastrowid
        else:
            pedido_id = carrinho["id"]
            if carrinho["loja_id"] != loja_id:
                cur.execute("UPDATE pedido SET loja_id = %s WHERE id = %s AND cliente_id = %s", (loja_id, pedido_id, cliente_id))
        if ja_no_carrinho:
            cur.execute("UPDATE itens_pedido SET quantidade = %s WHERE id = %s AND pedido_id = %s",
                        (nova, ja_no_carrinho["linha_id"], pedido_id))
        else:
            cur.execute("INSERT INTO itens_pedido (pedido_id, item_estoque_id, quantidade, preco_unitario) "
                        "VALUES (%s, %s, %s, %s)", (pedido_id, escolhida["id"], nova, produto["preco"]))
        _reprecificar(ctx, cur, pedido_id)
        ctx.conn.commit()
    except Exception:
        ctx.conn.rollback()
        raise
    finally:
        cur.close()
    return {"gravado": True, "acao": "adicionado", "carrinho": _situacao_do_carrinho(ctx, pedido_id)}


# ---------------------------------------------------------------------------
# alterar_item_carrinho
# ---------------------------------------------------------------------------
@ferramenta(
    nome="alterar_item_carrinho",
    descricao=(
        "Muda a quantidade de um produto que já está no carrinho do cliente logado. A quantidade informada é a NOVA "
        "quantidade total (não a diferença); 0 remove o item. Se o produto está no carrinho em mais de uma variação, "
        "informe cor e/ou tamanho. Não pede confirmação: é reversível."
    ),
    parametros={
        "produto_id": {"tipo": "integer", "obrigatorio": True, "descricao": "Id do produto que está no carrinho."},
        "quantidade": {"tipo": "integer", "obrigatorio": True,
                       "descricao": f"Nova quantidade total (0 a {MAX_QTD_ITEM}); 0 remove o item."},
        "cor": {"tipo": "string", "obrigatorio": False, "descricao": "Opcional. Cor da variação."},
        "tamanho": {"tipo": "string", "obrigatorio": False, "descricao": "Opcional. Tamanho da variação."},
    },
)
def alterar_item_carrinho(ctx, produto_id, quantidade, cor=None, tamanho=None):
    cliente_id = exigir_cliente(ctx)
    produto_id = exigir_inteiro(produto_id, "produto_id")
    quantidade = _quantidade(quantidade, 0)
    cor, tamanho = _opcional(cor, "cor"), _opcional(tamanho, "tamanho")

    carrinho = _carrinho_atual(ctx, cliente_id)
    linhas = _linhas(ctx, carrinho["id"]) if carrinho else []
    if not linhas:
        raise ErroFerramenta("CARRINHO_VAZIO", "O cliente não tem itens no carrinho.")
    alvo = [l for l in linhas if l["produto_id"] == produto_id and _bate(l["cor"], cor) and _bate(l["tamanho"], tamanho)]
    if not alvo:
        raise ErroFerramenta("ITEM_NAO_ESTA_NO_CARRINHO", "Esse produto não está no carrinho. "
                             f"Itens do carrinho: {[l['nome'] for l in linhas]}")
    if len(alvo) > 1:
        raise ErroFerramenta("VARIACAO_OBRIGATORIA", f"Esse produto está no carrinho em mais de uma variação: "
                             f"informe cor e/ou tamanho. Variações: {[_variacao(l) for l in alvo]}")
    linha = alvo[0]
    if quantidade > linha["estoque"]:
        raise ErroFerramenta("ESTOQUE_INSUFICIENTE", f"Só há {linha['estoque']} unidade(s) de '{linha['nome']}' nessa loja.")

    pedido_id = carrinho["id"]
    cur = ctx.conn.cursor()
    try:
        if quantidade == 0:
            cur.execute("DELETE FROM itens_pedido WHERE id = %s AND pedido_id = %s", (linha["linha_id"], pedido_id))
            if len(linhas) == 1:        # carrinho esvaziado: fica livre para qualquer loja
                cur.execute("UPDATE pedido SET loja_id = NULL WHERE id = %s AND cliente_id = %s", (pedido_id, cliente_id))
        else:
            cur.execute("UPDATE itens_pedido SET quantidade = %s WHERE id = %s AND pedido_id = %s",
                        (quantidade, linha["linha_id"], pedido_id))
        _reprecificar(ctx, cur, pedido_id)
        ctx.conn.commit()
    except Exception:
        ctx.conn.rollback()
        raise
    finally:
        cur.close()
    return {"gravado": True, "acao": "removido" if quantidade == 0 else "alterado",
            "carrinho": _situacao_do_carrinho(ctx, pedido_id)}


# ---------------------------------------------------------------------------
# finalizar_pedido
# ---------------------------------------------------------------------------
def _texto_do_endereco(e) -> str:
    """Mesmo formato dos pedidos que já existem: 'Rua X, 58 - Apto 3 - Bairro, Cidade/UF - CEP 00000-000'."""
    partes = f"{e['rua']}, {e['numero']}"
    if e["complemento"]:
        partes += f" - {e['complemento']}"
    if e["bairro"]:
        partes += f" - {e['bairro']}"
    partes += f", {e['cidade']}/{e['estado']}"
    if e["cep"]:
        partes += f" - CEP {e['cep']}"
    return partes


def _validar_finalizacao(ctx, cliente_id, endereco_id):
    """Todas as regras. Roda nas DUAS etapas (o estoque e os preços podem mudar entre elas)."""
    carrinho = _carrinho_atual(ctx, cliente_id)
    linhas = _linhas(ctx, carrinho["id"]) if carrinho else []
    if not linhas:
        raise ErroFerramenta("CARRINHO_VAZIO", "O carrinho está vazio: não há o que finalizar.")
    endereco = _consulta(ctx, "SELECT id, rua, numero, complemento, bairro, cep, cidade, estado FROM endereco "
                              "WHERE id = %s AND cliente_id = %s", (endereco_id, cliente_id), um=True)
    if endereco is None:      # endereço de outro cliente e endereço inexistente dão o MESMO erro
        raise ErroFerramenta("ENDERECO_NAO_ENCONTRADO",
                             "Não encontrei esse endereço entre os do cliente. Use listar_meus_enderecos.")
    for l in linhas:
        if not l["ativo"]:
            raise ErroFerramenta("PRODUTO_INDISPONIVEL", f"'{l['nome']}' não está mais à venda: remova do carrinho.")
    if len({l["loja_id"] for l in linhas}) > 1:
        raise ErroFerramenta("ITENS_DE_LOJAS_DIFERENTES",
                             "O carrinho mistura lojas. Remova os itens (alterar_item_carrinho com quantidade 0) "
                             "até sobrar uma loja só.")
    for l in linhas:
        if l["quantidade"] > l["estoque"]:
            raise ErroFerramenta("ESTOQUE_INSUFICIENTE",
                                 f"Só há {l['estoque']} unidade(s) de '{l['nome']}' e o carrinho tem {l['quantidade']}. "
                                 "Ajuste com alterar_item_carrinho.")
    itens, total = _resumo_linhas(linhas)
    loja_id = linhas[0]["loja_id"]
    resumo = {"pedido_id": carrinho["id"], "loja": _nome_loja(ctx, loja_id), "itens": itens, "total": dinheiro(total),
              "endereco_entrega": _texto_do_endereco(endereco),
              "frete": "não calculado nesta demonstração",
              "pagamento": "ao confirmar, será gerado um link de pagamento ILUSTRATIVO"}
    # O que o cliente viu: itens, quantidades, PREÇOS e total. Se algo mudar até a confirmação, o código não vale.
    amarrado = {"pedido_id": carrinho["id"], "endereco_id": endereco_id,
                "itens": [[l["item_estoque_id"], l["quantidade"], dinheiro(l["preco"])] for l in linhas],
                "total": dinheiro(total)}
    return carrinho, linhas, loja_id, resumo, amarrado


@ferramenta(
    nome="finalizar_pedido",
    descricao=(
        "Fecha o carrinho do cliente logado e o transforma em pedido aguardando pagamento, em DUAS ETAPAS. "
        "Etapa 1: chame SEM 'confirmacao'. Nada é gravado: volta o resumo (itens, total, loja, endereço) e um código. "
        "Mostre o resumo ao cliente e pergunte se confirma. Etapa 2: só depois que o cliente responder em uma nova "
        "mensagem, chame de novo com o MESMO endereco_id e confirmacao=<código>. Ao confirmar, o estoque é reservado "
        "e a ferramenta devolve um link de pagamento ILUSTRATIVO: o pedido fica aguardando pagamento (nesta "
        "demonstração nenhum pagamento é processado). O endereco_id vem de listar_meus_enderecos."
    ),
    parametros={
        "endereco_id": {"tipo": "integer", "obrigatorio": True,
                        "descricao": "Id do endereço de entrega (campo endereco_id de listar_meus_enderecos)."},
        "confirmacao": {"tipo": "string", "obrigatorio": False,
                        "descricao": "Só na etapa 2: o código recebido na etapa 1."},
    },
)
def finalizar_pedido(ctx, endereco_id, confirmacao=None):
    cliente_id = exigir_cliente(ctx)
    endereco_id = exigir_inteiro(endereco_id, "endereco_id")
    carrinho, linhas, loja_id, resumo, amarrado = _validar_finalizacao(ctx, cliente_id, endereco_id)

    if confirmacao is None:
        return propor(ctx, cliente_id, "finalizar_pedido", amarrado, resumo)

    conferir(ctx, cliente_id, "finalizar_pedido", amarrado, confirmacao)
    pedido_id = carrinho["id"]
    codigo = f"PD{agenda._agora():%y%m%d}{pedido_id:05d}"
    cur = ctx.conn.cursor()
    try:
        for l in linhas:
            # Baixa condicional: o banco só desconta se ainda houver estoque (e nunca deixa ficar negativo).
            cur.execute("UPDATE item_estoque SET quantidade = quantidade - %s WHERE id = %s AND quantidade >= %s",
                        (l["quantidade"], l["item_estoque_id"], l["quantidade"]))
            if cur.rowcount != 1:
                raise ErroFerramenta("ESTOQUE_INSUFICIENTE", f"'{l['nome']}' acabou de ficar sem estoque suficiente.")
        _reprecificar(ctx, cur, pedido_id)
        cur.execute("UPDATE pedido SET status = 'aguardando_pagamento', loja_id = %s, endereco_entrega = %s, "
                    "codigo_transacao = %s WHERE id = %s AND cliente_id = %s AND status = 'carrinho'",
                    (loja_id, resumo["endereco_entrega"], codigo, pedido_id, cliente_id))
        if cur.rowcount != 1:
            raise ErroFerramenta("PEDIDO_NAO_FINALIZAVEL", "O carrinho mudou de situação e não pôde ser finalizado.")
        ctx.conn.commit()
    except Exception:
        ctx.conn.rollback()        # tudo ou nada: nenhuma baixa de estoque fica pela metade
        raise
    finally:
        cur.close()
    return {"gravado": True, "pedido_id": pedido_id, "codigo_pedido": codigo, "status": "aguardando_pagamento",
            "total": resumo["total"], "resumo": resumo,
            "pagamento": {"ilustrativo": True, "link": LINK_PAGAMENTO.format(codigo=codigo),
                          "instrucao": "Mostre o link ao cliente e deixe claro que é ILUSTRATIVO: esta demonstração "
                                       "não processa pagamentos e o pedido segue aguardando pagamento."}}


# ---------------------------------------------------------------------------
# cancelar_pedido
# ---------------------------------------------------------------------------
@ferramenta(
    nome="cancelar_pedido",
    descricao=(
        "Cancela um pedido do cliente logado que ainda não foi pago (status carrinho ou aguardando_pagamento), em DUAS "
        "ETAPAS. Etapa 1: chame SEM 'confirmacao'. Nada é alterado: volta um resumo e um código. Mostre o resumo ao "
        "cliente e pergunte se confirma. Etapa 2: só depois que o cliente responder em uma nova mensagem, chame de "
        "novo com o MESMO pedido_id e confirmacao=<código>. Cancelar um pedido aguardando pagamento devolve o estoque. "
        "Pedido já pago ou em andamento não é cancelado por aqui. O pedido_id vem de listar_meus_pedidos."
    ),
    parametros={
        "pedido_id": {"tipo": "integer", "obrigatorio": True,
                      "descricao": "Id do pedido (campo pedido_id de listar_meus_pedidos)."},
        "confirmacao": {"tipo": "string", "obrigatorio": False,
                        "descricao": "Só na etapa 2: o código recebido na etapa 1."},
    },
)
def cancelar_pedido(ctx, pedido_id, confirmacao=None):
    cliente_id = exigir_cliente(ctx)
    pedido_id = exigir_inteiro(pedido_id, "pedido_id")

    pedido = _consulta(ctx, "SELECT id, status, codigo_transacao, loja_id FROM pedido WHERE id = %s AND cliente_id = %s",
                       (pedido_id, cliente_id), um=True)
    if pedido is None:      # de outro cliente ou inexistente: mesmo erro
        raise ErroFerramenta("PEDIDO_NAO_ENCONTRADO", "Não encontrei esse pedido entre os do cliente. Use listar_meus_pedidos.")
    status = pedido["status"]
    if status == "cancelado":
        raise ErroFerramenta("PEDIDO_NAO_CANCELAVEL", "Este pedido já está cancelado.")
    if status not in STATUS_CANCELAVEIS:
        raise ErroFerramenta("PEDIDO_NAO_CANCELAVEL",
                             f"Este pedido está '{status}' e não pode ser cancelado por aqui: o cliente deve falar com "
                             "o atendimento da loja.")

    linhas = _linhas(ctx, pedido_id)
    itens, total = _resumo_linhas(linhas)
    resumo = {"pedido_id": pedido_id, "codigo": pedido["codigo_transacao"], "status": status,
              "loja": _nome_loja(ctx, pedido["loja_id"]), "itens": itens, "total": dinheiro(total)}
    amarrado = {"pedido_id": pedido_id, "status": status}

    if confirmacao is None:
        return propor(ctx, cliente_id, "cancelar_pedido", amarrado, resumo)

    conferir(ctx, cliente_id, "cancelar_pedido", amarrado, confirmacao)
    cur = ctx.conn.cursor()
    try:
        # A troca de status vem PRIMEIRO e só vale se o pedido ainda está como foi mostrado: assim o estoque
        # nunca é devolvido duas vezes, nem para um pedido que acabou de ser pago.
        cur.execute("UPDATE pedido SET status = 'cancelado' WHERE id = %s AND cliente_id = %s AND status = %s",
                    (pedido_id, cliente_id, status))
        if cur.rowcount != 1:
            raise ErroFerramenta("PEDIDO_NAO_CANCELAVEL", "Este pedido mudou de situação e não pôde ser cancelado.")
        if status == "aguardando_pagamento":      # só nele o estoque tinha sido reservado
            for l in linhas:
                cur.execute("UPDATE item_estoque SET quantidade = quantidade + %s WHERE id = %s",
                            (l["quantidade"], l["item_estoque_id"]))
        ctx.conn.commit()
    except Exception:
        ctx.conn.rollback()
        raise
    finally:
        cur.close()
    return {"gravado": True, "pedido_id": pedido_id, "status": "cancelado", "resumo": resumo}