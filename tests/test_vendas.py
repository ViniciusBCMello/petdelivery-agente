"""Carrinho, finalizar_pedido e cancelar_pedido, com o banco de verdade (tudo é desfeito no fim de cada teste)."""
import dataclasses
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import mysql.connector
import pytest

from app.tools import especificacoes, executar
from app.tools import vendas as modulo_vendas
from app.tools.vendas import MAX_QTD_ITEM, _texto_do_endereco


# ------------------------------------------------------------------ apoio
def erro(r):
    assert r["ok"] is False, r
    return r["erro"]["codigo"]


def dinheiro(valor):
    return f"{Decimal(valor):.2f}"


@pytest.fixture()
def v(escrita):
    """Dois clientes com endereço e SEM carrinho + produtos reais para vender (preparo fixado no banco)."""
    env = escrita
    (cli, end), (cli2, end2) = env.sql("SELECT cliente_id, MIN(id) FROM endereco GROUP BY cliente_id ORDER BY cliente_id LIMIT 2")
    for c in (cli, cli2):
        env.sql("DELETE FROM itens_pedido WHERE pedido_id IN (SELECT id FROM pedido WHERE cliente_id = %s AND status = 'carrinho')", (c,))
        env.sql("DELETE FROM pedido WHERE cliente_id = %s AND status = 'carrinho'", (c,))

    def itens(sql):
        return [SimpleNamespace(produto_id=p, loja_id=l, estoque_id=i, estoque=q, nome=n, cor=c or None, tamanho=t or None)
                for p, l, i, q, n, c, t in env.sql(sql)]

    unicos = itens(
        "SELECT ie.produto_id, ie.loja_id, ie.id, ie.quantidade, p.nome, ie.cor, ie.tamanho FROM item_estoque ie "
        "JOIN produto p ON p.id = ie.produto_id WHERE p.ativo = 1 AND ie.quantidade BETWEEN 5 AND 30 "
        "AND (SELECT COUNT(*) FROM item_estoque x WHERE x.produto_id = ie.produto_id AND x.loja_id = ie.loja_id) = 1 "
        "ORDER BY ie.loja_id, ie.id")
    a = unicos[0]
    b = next(i for i in unicos if i.loja_id == a.loja_id and i.produto_id != a.produto_id)
    c = next(i for i in unicos if i.loja_id != a.loja_id)
    multi = env.sql("SELECT ie.produto_id, ie.loja_id FROM item_estoque ie JOIN produto p ON p.id = ie.produto_id "
                    "WHERE p.ativo = 1 GROUP BY ie.produto_id, ie.loja_id HAVING COUNT(*) > 1 AND MIN(ie.quantidade) >= 3 "
                    "ORDER BY ie.produto_id, ie.loja_id LIMIT 1")[0]
    variacoes = itens(f"SELECT ie.produto_id, ie.loja_id, ie.id, ie.quantidade, p.nome, ie.cor, ie.tamanho FROM item_estoque ie "
                      f"JOIN produto p ON p.id = ie.produto_id WHERE ie.produto_id = {multi[0]} AND ie.loja_id = {multi[1]} ORDER BY ie.id")
    env.conn.fixar()
    return SimpleNamespace(env=env, cli=cli, end=end, cli2=cli2, end2=end2, a=a, b=b, c=c, variacoes=variacoes,
                           ctx=env.como(cli), ctx2=env.como(cli2))


def add(ctx, item, qtd, **extra):
    corpo = {"produto_id": item.produto_id, "loja_id": item.loja_id, "quantidade": qtd, **extra}
    if "cor" not in extra and item.cor:
        corpo["cor"] = item.cor
    if "tamanho" not in extra and item.tamanho:
        corpo["tamanho"] = item.tamanho
    return executar("adicionar_ao_carrinho", corpo, ctx)


def estoque(env, item):
    return env.sql("SELECT quantidade FROM item_estoque WHERE id = %s", (item.estoque_id,))[0][0]


def preco(env, item):
    return env.sql("SELECT preco FROM produto WHERE id = %s", (item.produto_id,))[0][0]


def carrinhos(env, cliente):
    return env.sql("SELECT id, loja_id FROM pedido WHERE cliente_id = %s AND status = 'carrinho' ORDER BY id", (cliente,))


def linhas(env, pedido_id):
    return env.sql("SELECT item_estoque_id, quantidade, preco_unitario FROM itens_pedido WHERE pedido_id = %s ORDER BY id", (pedido_id,))


def pedido(env, pedido_id):
    return env.sql("SELECT status, loja_id, endereco_entrega, codigo_transacao, data_finalizacao FROM pedido WHERE id = %s", (pedido_id,))[0]


def fechar(v, cliente=None, endereco=None, turno=1):
    """Etapa 1 de finalizar_pedido. Devolve (resposta, código)."""
    cliente, endereco = cliente or v.cli, endereco or v.end
    r = executar("finalizar_pedido", {"endereco_id": endereco}, v.env.como(cliente, turno))
    return r, (r["dados"]["codigo_confirmacao"] if r["ok"] else None)


def confirmar(v, codigo, cliente=None, endereco=None, turno=2):
    cliente, endereco = cliente or v.cli, endereco or v.end
    return executar("finalizar_pedido", {"endereco_id": endereco, "confirmacao": codigo}, v.env.como(cliente, turno))


def pedido_aguardando(v, *pares):
    """Monta e finaliza um pedido pelo caminho normal. Devolve o pedido_id."""
    for item, qtd in pares:
        assert add(v.ctx, item, qtd)["ok"]
    _, cod = fechar(v)
    r = confirmar(v, cod)
    assert r["ok"], r
    return r["dados"]["pedido_id"]


# ============================================================ adicionar_ao_carrinho
def test_cria_o_carrinho_preso_a_loja_e_devolve_o_resumo(v):
    r = add(v.ctx, v.a, 2)
    assert r["ok"] and r["dados"]["gravado"] is True and r["dados"]["acao"] == "adicionado"
    cart = r["dados"]["carrinho"]
    assert cart["total"] == dinheiro(preco(v.env, v.a) * 2) and cart["itens"][0]["quantidade"] == 2
    assert {"produto_id", "nome", "preco_unitario", "subtotal"} <= set(cart["itens"][0])
    (pid, loja), = carrinhos(v.env, v.cli)
    assert loja == v.a.loja_id and linhas(v.env, pid) == [(v.a.estoque_id, 2, preco(v.env, v.a))]
    assert v.env.conn.commits == 1                                   # e a gravação foi efetivada


def test_adicionar_nao_mexe_no_estoque(v):
    add(v.ctx, v.a, 3)
    assert estoque(v.env, v.a) == v.a.estoque                        # estoque só é abatido ao FINALIZAR


def test_adicionar_de_novo_soma_na_mesma_linha(v):
    add(v.ctx, v.a, 2)
    r = add(v.ctx, v.a, 3)
    assert r["dados"]["carrinho"]["itens"][0]["quantidade"] == 5 and len(r["dados"]["carrinho"]["itens"]) == 1
    (pid, _), = carrinhos(v.env, v.cli)
    assert linhas(v.env, pid)[0][1] == 5


def test_varios_produtos_somam_no_total(v):
    add(v.ctx, v.a, 2)
    r = add(v.ctx, v.b, 1)
    esperado = preco(v.env, v.a) * 2 + preco(v.env, v.b)
    assert r["dados"]["carrinho"]["total"] == dinheiro(esperado) and len(r["dados"]["carrinho"]["itens"]) == 2


def test_nao_aceita_mais_do_que_o_estoque(v):
    assert erro(add(v.ctx, v.a, v.a.estoque + 1)) == "ESTOQUE_INSUFICIENTE"
    assert carrinhos(v.env, v.cli) == []                             # e nem cria carrinho à toa
    assert add(v.ctx, v.a, v.a.estoque)["ok"]
    r = add(v.ctx, v.a, 1)                                           # o que já está no carrinho conta
    assert erro(r) == "ESTOQUE_INSUFICIENTE" and "já estão no carrinho" in r["erro"]["mensagem"]


@pytest.mark.parametrize("ruim", [0, -1, "muitas", None, True, 2.5, MAX_QTD_ITEM + 1])
def test_quantidade_invalida(v, ruim):
    assert erro(add(v.ctx, v.a, ruim)) == "PARAMETRO_INVALIDO"
    assert carrinhos(v.env, v.cli) == []


def test_produto_loja_e_variacao_inexistentes(v):
    assert erro(executar("adicionar_ao_carrinho", {"produto_id": 999999, "loja_id": v.a.loja_id, "quantidade": 1}, v.ctx)) == "PRODUTO_NAO_ENCONTRADO"
    assert erro(executar("adicionar_ao_carrinho", {"produto_id": v.a.produto_id, "loja_id": 999999, "quantidade": 1}, v.ctx)) == "LOJA_NAO_ENCONTRADA"
    sem_venda = v.env.sql("SELECT l.id FROM loja l WHERE NOT EXISTS (SELECT 1 FROM item_estoque ie WHERE ie.loja_id = l.id AND ie.produto_id = %s) LIMIT 1", (v.a.produto_id,))
    if sem_venda:
        r = executar("adicionar_ao_carrinho", {"produto_id": v.a.produto_id, "loja_id": sem_venda[0][0], "quantidade": 1}, v.ctx)
        assert erro(r) == "PRODUTO_NAO_VENDIDO_NA_LOJA"


def test_produto_inativo_nao_entra_no_carrinho(v):
    v.env.sql("UPDATE produto SET ativo = 0 WHERE id = %s", (v.a.produto_id,))
    assert erro(add(v.ctx, v.a, 1)) == "PRODUTO_INDISPONIVEL"


def test_variacao_obrigatoria_lista_as_opcoes(v):
    ref = v.variacoes[0]
    r = executar("adicionar_ao_carrinho", {"produto_id": ref.produto_id, "loja_id": ref.loja_id, "quantidade": 1}, v.ctx)
    assert erro(r) == "VARIACAO_OBRIGATORIA" and "Opções" in r["erro"]["mensagem"]
    ruim = executar("adicionar_ao_carrinho", {"produto_id": ref.produto_id, "loja_id": ref.loja_id, "quantidade": 1,
                                              "cor": "cor-que-nao-existe"}, v.ctx)
    assert erro(ruim) == "VARIACAO_NAO_ENCONTRADA"
    assert carrinhos(v.env, v.cli) == []


def test_variacao_informada_entra_e_ignora_maiusculas(v):
    ref = v.variacoes[0]
    extra = {}
    if ref.cor:
        extra["cor"] = ref.cor.upper()
    if ref.tamanho:
        extra["tamanho"] = ref.tamanho.lower()
    r = executar("adicionar_ao_carrinho", {"produto_id": ref.produto_id, "loja_id": ref.loja_id, "quantidade": 1, **extra}, v.ctx)
    if r["ok"]:
        (pid, _), = carrinhos(v.env, v.cli)
        assert linhas(v.env, pid)[0][0] == ref.estoque_id
    else:   # a combinação pode ainda deixar mais de uma variação: então a ferramenta tem de pedir o que falta
        assert erro(r) == "VARIACAO_OBRIGATORIA"


def test_carrinho_e_de_uma_loja_so(v):
    add(v.ctx, v.a, 1)
    r = add(v.ctx, v.c, 1)
    assert erro(r) == "LOJA_DIFERENTE_DO_CARRINHO" and "uma loja só" in r["erro"]["mensagem"]
    (pid, _), = carrinhos(v.env, v.cli)
    assert len(linhas(v.env, pid)) == 1


def test_esvaziado_o_carrinho_aceita_outra_loja(v):
    add(v.ctx, v.a, 1)
    alt = executar("alterar_item_carrinho", {"produto_id": v.a.produto_id, "quantidade": 0}, v.ctx)
    assert alt["ok"]
    assert add(v.ctx, v.c, 1)["ok"]
    (pid, loja), = carrinhos(v.env, v.cli)
    assert loja == v.c.loja_id


def test_preco_do_carrinho_e_sempre_o_de_hoje(v):
    add(v.ctx, v.a, 2)
    v.env.sql("UPDATE produto SET preco = preco + 10 WHERE id = %s", (v.a.produto_id,))
    r = add(v.ctx, v.b, 1)                                           # qualquer alteração reprecifica o carrinho todo
    assert r["dados"]["carrinho"]["itens"][0]["preco_unitario"] == dinheiro(preco(v.env, v.a))
    (pid, _), = carrinhos(v.env, v.cli)
    assert linhas(v.env, pid)[0][2] == preco(v.env, v.a)


def test_com_dois_carrinhos_usa_o_mais_recente(v):
    v.env.sql("INSERT INTO pedido (cliente_id, status) VALUES (%s, 'carrinho')", (v.cli,))
    v.env.sql("INSERT INTO pedido (cliente_id, status) VALUES (%s, 'carrinho')", (v.cli,))
    antigo, novo = [c[0] for c in carrinhos(v.env, v.cli)]
    v.env.conn.fixar()
    add(v.ctx, v.a, 1)
    assert linhas(v.env, antigo) == [] and len(linhas(v.env, novo)) == 1


def test_carrinho_antigo_sem_loja_vira_carrinho_da_loja_do_item(v):
    """Os carrinhos que já existem nos dados têm loja_id vazio."""
    v.env.sql("INSERT INTO pedido (cliente_id, status) VALUES (%s, 'carrinho')", (v.cli,))
    pid = v.env.sql("SELECT MAX(id) FROM pedido")[0][0]
    v.env.sql("INSERT INTO itens_pedido (pedido_id, item_estoque_id, quantidade, preco_unitario) VALUES (%s, %s, 1, %s)",
              (pid, v.a.estoque_id, preco(v.env, v.a)))
    v.env.conn.fixar()
    assert add(v.ctx, v.b, 1)["ok"]                                  # mesma loja do item que já estava lá
    assert v.env.sql("SELECT loja_id FROM pedido WHERE id = %s", (pid,))[0][0] == v.a.loja_id
    assert erro(add(v.ctx, v.c, 1)) == "LOJA_DIFERENTE_DO_CARRINHO"


def test_cada_cliente_so_mexe_no_proprio_carrinho(v):
    add(v.ctx2, v.a, 1)
    antes = carrinhos(v.env, v.cli2)
    add(v.ctx, v.b, 2)
    (pid2, _), = antes
    assert linhas(v.env, pid2) == [(v.a.estoque_id, 1, preco(v.env, v.a))]
    assert carrinhos(v.env, v.cli) != antes


def test_adicionar_exige_login_e_nao_aceita_cliente_id(v):
    assert erro(add(v.env.como(None), v.a, 1)) == "NAO_AUTENTICADO"
    assert erro(add(v.ctx, v.a, 1, cliente_id=v.cli2)) == "PARAMETRO_INVALIDO"


# ============================================================ alterar_item_carrinho
def alterar(ctx, item, qtd, **extra):
    return executar("alterar_item_carrinho", {"produto_id": item.produto_id, "quantidade": qtd, **extra}, ctx)


def test_altera_para_a_nova_quantidade_total(v):
    add(v.ctx, v.a, 2)
    commits = v.env.conn.commits
    r = alterar(v.ctx, v.a, 4)
    assert r["ok"] and r["dados"]["acao"] == "alterado" and r["dados"]["carrinho"]["itens"][0]["quantidade"] == 4
    assert v.env.conn.commits == commits + 1


def test_quantidade_zero_remove_o_item(v):
    add(v.ctx, v.a, 2)
    add(v.ctx, v.b, 1)
    r = alterar(v.ctx, v.a, 0)
    assert r["dados"]["acao"] == "removido" and [i["produto_id"] for i in r["dados"]["carrinho"]["itens"]] == [v.b.produto_id]


def test_remover_o_ultimo_item_libera_a_loja(v):
    add(v.ctx, v.a, 1)
    alterar(v.ctx, v.a, 0)
    (pid, loja), = carrinhos(v.env, v.cli)
    assert loja is None and linhas(v.env, pid) == []


def test_alterar_nao_passa_do_estoque(v):
    add(v.ctx, v.a, 1)
    assert erro(alterar(v.ctx, v.a, v.a.estoque + 1)) == "ESTOQUE_INSUFICIENTE"
    assert alterar(v.ctx, v.a, v.a.estoque)["ok"]


def test_alterar_sem_carrinho_ou_item_fora_do_carrinho(v):
    assert erro(alterar(v.ctx, v.a, 1)) == "CARRINHO_VAZIO"
    add(v.ctx, v.a, 1)
    assert erro(alterar(v.ctx, v.b, 1)) == "ITEM_NAO_ESTA_NO_CARRINHO"


def test_alterar_variacao_ambigua_pede_cor_ou_tamanho(v):
    ref = v.variacoes
    for item in ref[:2]:
        assert add(v.ctx, item, 1)["ok"]
    r = executar("alterar_item_carrinho", {"produto_id": ref[0].produto_id, "quantidade": 2}, v.ctx)
    assert erro(r) == "VARIACAO_OBRIGATORIA"


@pytest.mark.parametrize("ruim", [-1, "x", None, True, MAX_QTD_ITEM + 1])
def test_alterar_quantidade_invalida(v, ruim):
    add(v.ctx, v.a, 1)
    assert erro(alterar(v.ctx, v.a, ruim)) == "PARAMETRO_INVALIDO"


def test_alterar_so_mexe_no_proprio_carrinho(v):
    add(v.ctx2, v.a, 3)
    assert erro(alterar(v.ctx, v.a, 1)) == "CARRINHO_VAZIO"          # o carrinho do outro cliente não é visível
    (pid2, _), = carrinhos(v.env, v.cli2)
    assert linhas(v.env, pid2)[0][1] == 3


def test_alterar_exige_login_e_nao_aceita_cliente_id(v):
    add(v.ctx, v.a, 1)
    assert erro(alterar(v.env.como(None), v.a, 1)) == "NAO_AUTENTICADO"
    assert erro(alterar(v.ctx, v.a, 1, cliente_id=v.cli2)) == "PARAMETRO_INVALIDO"


# ============================================================ finalizar_pedido
def test_a_proposta_nao_grava_e_mostra_o_que_sera_comprado(v):
    add(v.ctx, v.a, 2)
    commits = v.env.conn.commits
    r, _ = fechar(v)
    assert r["ok"] and r["dados"]["gravado"] is False and r["dados"]["requer_confirmacao"]
    resumo = r["dados"]["resumo"]
    assert resumo["total"] == dinheiro(preco(v.env, v.a) * 2) and resumo["itens"][0]["quantidade"] == 2
    assert resumo["endereco_entrega"] and resumo["loja"]
    assert resumo["frete"] and "ILUSTRATIVO" in resumo["pagamento"]
    (pid, _), = carrinhos(v.env, v.cli)                              # continua carrinho
    assert pedido(v.env, pid)[0] == "carrinho" and estoque(v.env, v.a) == v.a.estoque
    assert v.env.conn.commits == commits                             # a proposta não faz commit


def test_confirmar_cria_o_pedido_aguardando_pagamento(v):
    add(v.ctx, v.a, 2)
    add(v.ctx, v.b, 1)
    commits = v.env.conn.commits
    _, cod = fechar(v)
    r = confirmar(v, cod)
    d = r["dados"]
    assert r["ok"] and d["gravado"] is True and d["status"] == "aguardando_pagamento"
    status, loja, endereco, codigo, finalizacao = pedido(v.env, d["pedido_id"])
    assert status == "aguardando_pagamento" and loja == v.a.loja_id and finalizacao is None
    assert codigo == d["codigo_pedido"] == f"PD{datetime.now():%y%m%d}{d['pedido_id']:05d}"
    assert endereco == d["resumo"]["endereco_entrega"]
    assert estoque(v.env, v.a) == v.a.estoque - 2 and estoque(v.env, v.b) == v.b.estoque - 1
    assert d["total"] == dinheiro(preco(v.env, v.a) * 2 + preco(v.env, v.b))
    assert v.env.conn.commits == commits + 1                         # só a confirmação faz commit
    assert carrinhos(v.env, v.cli) == []                             # o carrinho virou pedido


def test_pagamento_e_ilustrativo_e_o_pedido_nunca_vira_pago(v):
    pid = pedido_aguardando(v, (v.a, 1))
    link = executar("consultar_pedido", {"pedido_id": pid}, v.ctx)
    assert link["ok"] and link["dados"]["status"] == "aguardando_pagamento"
    assert v.env.sql("SELECT COUNT(*) FROM pagamento WHERE pedido_id = %s", (pid,))[0][0] == 0
    cod = pedido(v.env, pid)[3]
    r = executar("finalizar_pedido", {"endereco_id": v.end}, v.ctx)
    assert erro(r) == "CARRINHO_VAZIO"                               # e não há como "pagar" por nenhuma ferramenta
    assert not any("pag" in e["name"] for e in especificacoes())      # não existe ferramenta que marque como pago
    assert cod.startswith("PD")


def test_link_de_pagamento_e_marcado_como_ilustrativo(v):
    add(v.ctx, v.a, 1)
    _, cod = fechar(v)
    pag = confirmar(v, cod)["dados"]["pagamento"]
    assert pag["ilustrativo"] is True and pag["link"].startswith("https://pagamento.petdelivery.example/pedido/PD")
    assert "ILUSTRATIVO" in pag["instrucao"]


def test_endereco_congelado_no_mesmo_formato_dos_pedidos_existentes(v):
    pedidos = v.env.sql("SELECT cliente_id, endereco_entrega FROM pedido WHERE status IN ('aguardando_pagamento', 'pago') AND endereco_entrega IS NOT NULL")
    assert pedidos
    for cliente, texto in pedidos:
        cur = v.env.conn.cursor(dictionary=True)
        cur.execute("SELECT rua, numero, complemento, bairro, cep, cidade, estado FROM endereco WHERE cliente_id = %s", (cliente,))
        textos = [_texto_do_endereco(e) for e in cur.fetchall()]
        cur.close()
        assert texto in textos, (texto, textos)


def test_codigo_so_vale_uma_vez(v):
    add(v.ctx, v.a, 1)
    _, cod = fechar(v)
    assert confirmar(v, cod)["ok"]
    assert erro(confirmar(v, cod, turno=3)) in ("CONFIRMACAO_INVALIDA", "CARRINHO_VAZIO")
    assert v.env.sql("SELECT COUNT(*) FROM pedido WHERE cliente_id = %s AND status = 'aguardando_pagamento' AND codigo_transacao LIKE %s",
                     (v.cli, f"PD{datetime.now():%y%m%d}%"))[0][0] == 1


def test_confirmar_na_mesma_mensagem_e_recusado(v):
    add(v.ctx, v.a, 1)
    _, cod = fechar(v, turno=5)
    r = confirmar(v, cod, turno=5)
    assert erro(r) == "CONFIRMACAO_PREMATURA"
    assert estoque(v.env, v.a) == v.a.estoque


def test_endereco_diferente_do_resumo_e_recusado(v):
    outros = v.env.sql("SELECT id FROM endereco WHERE cliente_id = %s AND id <> %s", (v.cli, v.end))
    add(v.ctx, v.a, 1)
    _, cod = fechar(v)
    if outros:
        assert erro(confirmar(v, cod, endereco=outros[0][0])) == "CONFIRMACAO_DIFERENTE"
    assert confirmar(v, cod)["ok"]


def test_carrinho_que_mudou_depois_do_resumo_invalida_a_confirmacao(v):
    add(v.ctx, v.a, 1)
    _, cod = fechar(v)
    add(v.ctx, v.b, 1)                                               # o cliente (ou o modelo) mexeu no carrinho
    assert erro(confirmar(v, cod)) == "CONFIRMACAO_DIFERENTE"
    (pid, _), = carrinhos(v.env, v.cli)
    assert pedido(v.env, pid)[0] == "carrinho" and estoque(v.env, v.a) == v.a.estoque


def test_troca_de_produto_com_o_mesmo_total_tambem_invalida_a_confirmacao(v):
    """O código amarra O QUE o cliente viu, não só o valor: trocar um item por outro de mesmo preço não passa."""
    v.env.sql("UPDATE produto SET preco = %s WHERE id = %s", (preco(v.env, v.a), v.b.produto_id))
    add(v.ctx, v.a, 1)
    r, cod = fechar(v)
    total_visto = r["dados"]["resumo"]["total"]
    alterar(v.ctx, v.a, 0)
    add(v.ctx, v.b, 1)
    r2, _ = fechar(v, turno=2)
    assert r2["dados"]["resumo"]["total"] == total_visto             # mesmo total, produto diferente
    assert erro(confirmar(v, cod, turno=3)) == "CONFIRMACAO_DIFERENTE"
    assert estoque(v.env, v.a) == v.a.estoque and estoque(v.env, v.b) == v.b.estoque


def test_preco_que_mudou_depois_do_resumo_invalida_a_confirmacao(v):
    add(v.ctx, v.a, 1)
    _, cod = fechar(v)
    v.env.sql("UPDATE produto SET preco = preco + 5 WHERE id = %s", (v.a.produto_id,))
    assert erro(confirmar(v, cod)) == "CONFIRMACAO_DIFERENTE"


def test_codigo_de_outro_cliente_e_recusado(v):
    add(v.ctx, v.a, 1)
    add(v.ctx2, v.b, 1)
    _, cod = fechar(v)
    assert erro(confirmar(v, cod, cliente=v.cli2, endereco=v.end2)) == "CONFIRMACAO_INVALIDA"


def test_codigo_expirado_e_recusado(v):
    add(v.ctx, v.a, 1)
    _, cod = fechar(v)
    v.env.relogio.avancar(minutes=11)
    assert erro(confirmar(v, cod)) == "CONFIRMACAO_INVALIDA"


def test_carrinho_vazio_e_endereco_alheio(v):
    r, _ = fechar(v)
    assert erro(r) == "CARRINHO_VAZIO"
    add(v.ctx, v.a, 1)
    alheio, _ = fechar(v, endereco=v.end2)
    inexistente, _ = fechar(v, endereco=999999)
    assert erro(alheio) == "ENDERECO_NAO_ENCONTRADO" and alheio == inexistente


def test_produto_que_saiu_de_linha_ou_estoque_que_acabou_barram_nas_duas_etapas(v):
    add(v.ctx, v.a, 2)
    _, cod = fechar(v)
    v.env.sql("UPDATE item_estoque SET quantidade = 1 WHERE id = %s", (v.a.estoque_id,))        # acabou depois do resumo
    assert erro(confirmar(v, cod)) == "ESTOQUE_INSUFICIENTE"
    assert erro(fechar(v, turno=3)[0]) == "ESTOQUE_INSUFICIENTE"
    v.env.sql("UPDATE item_estoque SET quantidade = %s WHERE id = %s", (v.a.estoque, v.a.estoque_id))
    v.env.sql("UPDATE produto SET ativo = 0 WHERE id = %s", (v.a.produto_id,))
    assert erro(fechar(v, turno=4)[0]) == "PRODUTO_INDISPONIVEL"


def test_carrinho_antigo_com_lojas_misturadas_nao_finaliza(v):
    add(v.ctx, v.a, 1)
    (pid, _), = carrinhos(v.env, v.cli)
    v.env.sql("INSERT INTO itens_pedido (pedido_id, item_estoque_id, quantidade, preco_unitario) VALUES (%s, %s, 1, %s)",
              (pid, v.c.estoque_id, preco(v.env, v.c)))
    assert erro(fechar(v)[0]) == "ITENS_DE_LOJAS_DIFERENTES"


def test_tudo_ou_nada_se_o_estoque_acabar_no_meio(v, monkeypatch):
    """Última linha de defesa: com a validação da aplicação 'enganada', a baixa condicional do banco segura e desfaz tudo."""
    add(v.ctx, v.a, 1)
    add(v.ctx, v.b, 2)
    v.env.conn.fixar()
    r, cod = fechar(v)
    velha = modulo_vendas._validar_finalizacao
    guardado = velha(v.ctx, v.cli, v.end)                            # o retrato de quando tudo estava livre
    v.env.sql("UPDATE item_estoque SET quantidade = 0 WHERE id = %s", (v.b.estoque_id,))        # o 2º item acaba
    v.env.conn.fixar()
    monkeypatch.setattr(modulo_vendas, "_validar_finalizacao", lambda *a, **k: guardado)
    res = confirmar(v, cod)
    assert erro(res) == "ESTOQUE_INSUFICIENTE"
    assert estoque(v.env, v.a) == v.a.estoque                        # a baixa do 1º item foi desfeita
    (pid, _), = carrinhos(v.env, v.cli)
    assert pedido(v.env, pid)[0] == "carrinho"


def test_o_banco_nunca_deixa_o_estoque_ficar_negativo(v):
    with pytest.raises(mysql.connector.Error):
        v.env.sql("UPDATE item_estoque SET quantidade = quantidade - %s WHERE id = %s", (v.a.estoque + 1, v.a.estoque_id))


def test_o_banco_nao_aceita_item_repetido_nem_quantidade_zero(v):
    add(v.ctx, v.a, 1)
    (pid, _), = carrinhos(v.env, v.cli)
    with pytest.raises(mysql.connector.Error):
        v.env.sql("INSERT INTO itens_pedido (pedido_id, item_estoque_id, quantidade, preco_unitario) VALUES (%s, %s, 1, 1)", (pid, v.a.estoque_id))
    with pytest.raises(mysql.connector.Error):
        v.env.sql("INSERT INTO itens_pedido (pedido_id, item_estoque_id, quantidade, preco_unitario) VALUES (%s, %s, 0, 1)", (pid, v.b.estoque_id))


def test_finalizar_exige_login_cofre_e_nao_aceita_cliente_id(v):
    add(v.ctx, v.a, 1)
    assert erro(executar("finalizar_pedido", {"endereco_id": v.end}, v.env.como(None))) == "NAO_AUTENTICADO"
    assert erro(executar("finalizar_pedido", {"endereco_id": v.end, "cliente_id": v.cli2}, v.ctx)) == "PARAMETRO_INVALIDO"
    sem_cofre = dataclasses.replace(v.ctx, confirmacoes=None)
    assert erro(executar("finalizar_pedido", {"endereco_id": v.end}, sem_cofre)) == "CONFIRMACAO_INDISPONIVEL"


# ============================================================ cancelar_pedido
def cancelar(v, pedido_id, codigo=None, cliente=None, turno=1):
    corpo = {"pedido_id": pedido_id, **({"confirmacao": codigo} if codigo else {})}
    return executar("cancelar_pedido", corpo, v.env.como(cliente or v.cli, turno))


def test_cancelar_aguardando_pagamento_devolve_o_estoque(v):
    pid = pedido_aguardando(v, (v.a, 2), (v.b, 1))
    assert estoque(v.env, v.a) == v.a.estoque - 2
    prop = cancelar(v, pid)
    assert prop["ok"] and prop["dados"]["gravado"] is False and pedido(v.env, pid)[0] == "aguardando_pagamento"
    commits = v.env.conn.commits
    r = cancelar(v, pid, prop["dados"]["codigo_confirmacao"], turno=2)
    assert r["ok"] and r["dados"]["status"] == "cancelado" and pedido(v.env, pid)[0] == "cancelado"
    assert estoque(v.env, v.a) == v.a.estoque and estoque(v.env, v.b) == v.b.estoque       # tudo de volta
    assert v.env.conn.commits == commits + 1


def test_ciclo_completo_deixa_o_estoque_exatamente_como_estava(v):
    antes = v.env.sql("SELECT SUM(quantidade) FROM item_estoque")[0][0]
    pid = pedido_aguardando(v, (v.a, 3), (v.b, 2))
    depois = v.env.sql("SELECT SUM(quantidade) FROM item_estoque")[0][0]
    assert antes - depois == 5
    cod = cancelar(v, pid)["dados"]["codigo_confirmacao"]
    cancelar(v, pid, cod, turno=2)
    assert v.env.sql("SELECT SUM(quantidade) FROM item_estoque")[0][0] == antes


def test_cancelar_carrinho_descarta_sem_mexer_no_estoque(v):
    add(v.ctx, v.a, 2)
    (pid, _), = carrinhos(v.env, v.cli)
    cod = cancelar(v, pid)["dados"]["codigo_confirmacao"]
    assert cancelar(v, pid, cod, turno=2)["ok"]
    assert pedido(v.env, pid)[0] == "cancelado" and estoque(v.env, v.a) == v.a.estoque


def test_estoque_nunca_e_devolvido_duas_vezes(v):
    pid = pedido_aguardando(v, (v.a, 2))
    cod = cancelar(v, pid)["dados"]["codigo_confirmacao"]
    assert cancelar(v, pid, cod, turno=2)["ok"]
    assert erro(cancelar(v, pid, turno=3)) == "PEDIDO_NAO_CANCELAVEL"        # já cancelado: nem gera novo resumo
    assert erro(cancelar(v, pid, cod, turno=3)) in ("PEDIDO_NAO_CANCELAVEL", "CONFIRMACAO_INVALIDA")
    assert estoque(v.env, v.a) == v.a.estoque


def test_cancelar_no_mesmo_turno_e_recusado(v):
    pid = pedido_aguardando(v, (v.a, 1))
    cod = cancelar(v, pid, turno=5)["dados"]["codigo_confirmacao"]
    assert erro(cancelar(v, pid, cod, turno=5)) == "CONFIRMACAO_PREMATURA"
    assert pedido(v.env, pid)[0] == "aguardando_pagamento" and estoque(v.env, v.a) == v.a.estoque - 1


def test_pedido_pago_no_meio_tempo_nao_e_cancelado_nem_devolve_estoque(v):
    pid = pedido_aguardando(v, (v.a, 2))
    cod = cancelar(v, pid)["dados"]["codigo_confirmacao"]
    v.env.sql("UPDATE pedido SET status = 'pago' WHERE id = %s", (pid,))     # o pagamento entrou depois do resumo
    assert erro(cancelar(v, pid, cod, turno=2)) == "PEDIDO_NAO_CANCELAVEL"
    assert estoque(v.env, v.a) == v.a.estoque - 2


def test_so_cancela_carrinho_ou_aguardando_pagamento(escrita):
    for status in ("pago", "em_separacao", "em_entrega", "entregue"):
        cli, pid = escrita.sql("SELECT cliente_id, id FROM pedido WHERE status = %s LIMIT 1", (status,))[0]
        r = executar("cancelar_pedido", {"pedido_id": pid}, escrita.como(cli))
        assert erro(r) == "PEDIDO_NAO_CANCELAVEL" and "atendimento" in r["erro"]["mensagem"], status
        assert escrita.sql("SELECT status FROM pedido WHERE id = %s", (pid,))[0][0] == status


def test_pedido_ja_cancelado_dos_dados(escrita):
    cli, pid = escrita.sql("SELECT cliente_id, id FROM pedido WHERE status = 'cancelado' LIMIT 1")[0]
    r = executar("cancelar_pedido", {"pedido_id": pid}, escrita.como(cli))
    assert erro(r) == "PEDIDO_NAO_CANCELAVEL" and "já está cancelado" in r["erro"]["mensagem"]


def test_pedido_de_outro_cliente_e_igual_a_inexistente(v):
    pid = pedido_aguardando(v, (v.a, 1))
    alheio = cancelar(v, pid, cliente=v.cli2)
    inexistente = cancelar(v, 999999, cliente=v.cli2)
    assert erro(alheio) == "PEDIDO_NAO_ENCONTRADO" and alheio == inexistente
    assert pedido(v.env, pid)[0] == "aguardando_pagamento"


def test_codigo_de_outro_cliente_ou_de_outra_acao_nao_cancela(v):
    pid = pedido_aguardando(v, (v.a, 1))
    cod = cancelar(v, pid)["dados"]["codigo_confirmacao"]
    assert erro(cancelar(v, pid, cod, cliente=v.cli2, turno=2)) == "PEDIDO_NAO_ENCONTRADO"
    add(v.ctx, v.b, 1)
    _, cod_finalizar = fechar(v, turno=3)
    assert erro(cancelar(v, pid, cod_finalizar, turno=4)) == "CONFIRMACAO_INVALIDA"
    assert pedido(v.env, pid)[0] == "aguardando_pagamento"


def test_cancelar_exige_login_e_nao_aceita_cliente_id(v):
    pid = pedido_aguardando(v, (v.a, 1))
    assert erro(executar("cancelar_pedido", {"pedido_id": pid}, v.env.como(None))) == "NAO_AUTENTICADO"
    assert erro(executar("cancelar_pedido", {"pedido_id": pid, "cliente_id": 1}, v.ctx)) == "PARAMETRO_INVALIDO"