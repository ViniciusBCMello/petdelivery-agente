"""Ferramentas de catálogo: buscar_produtos e consultar_estoque (somente leitura)."""
from .base import (ErroFerramenta, dinheiro, escapar_like, exigir_inteiro, exigir_texto, ferramenta)

MAX_RESULTADOS = 10
MAX_PALAVRAS = 6


@ferramenta(
    nome="buscar_produtos",
    descricao=(
        "Procura produtos ATIVOS do catálogo por palavras (nome, categoria, tipo, cor ou tamanho). "
        "Devolve até 10 produtos com id, nome, preço, categoria, tipo e variações. "
        "Use antes de consultar o estoque, para descobrir o produto_id."
    ),
    parametros={
        "termo": {
            "tipo": "string",
            "obrigatorio": True,
            "descricao": "Palavras da busca, por exemplo: 'ração gatos filhotes' ou 'coleira azul M'.",
        },
    },
)
def buscar_produtos(ctx, termo):
    termo = exigir_texto(termo, "termo", max_len=80)
    palavras = termo.split()[:MAX_PALAVRAS]

    # Cada palavra precisa aparecer em algum lugar do produto (AND entre palavras).
    # Os valores digitados NUNCA entram no texto do SQL: só como parâmetros (%s).
    filtros, params = [], []
    for palavra in palavras:
        padrao = f"%{escapar_like(palavra)}%"
        filtros.append(
            "(p.nome LIKE %s OR c.nome LIKE %s OR t.nome LIKE %s OR EXISTS ("
            "SELECT 1 FROM item_estoque ie WHERE ie.produto_id = p.id "
            "AND (ie.tamanho LIKE %s OR ie.cor LIKE %s)))"
        )
        params += [padrao] * 5

    sql = (
        "SELECT p.id, p.nome, p.preco, c.nome AS categoria, t.nome AS tipo "
        "FROM produto p JOIN categoria c ON c.id = p.categoria_id JOIN tipo t ON t.id = p.tipo_id "
        "WHERE p.ativo = 1 AND " + " AND ".join(filtros) + " ORDER BY p.nome LIMIT %s"
    )
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params + [MAX_RESULTADOS + 1])      # +1 para saber se ha mais
        linhas = cur.fetchall()
        ha_mais = len(linhas) > MAX_RESULTADOS
        linhas = linhas[:MAX_RESULTADOS]

        variacoes = {}
        if linhas:
            ids = [l["id"] for l in linhas]
            marcadores = ", ".join(["%s"] * len(ids))
            cur.execute(
                "SELECT DISTINCT produto_id, cor, tamanho FROM item_estoque "
                f"WHERE produto_id IN ({marcadores}) ORDER BY produto_id, cor, tamanho", ids)
            for v in cur.fetchall():
                variacoes.setdefault(v["produto_id"], []).append({"cor": v["cor"], "tamanho": v["tamanho"]})
    finally:
        cur.close()

    produtos = [
        {"id": l["id"], "nome": l["nome"], "preco": dinheiro(l["preco"]),
         "categoria": l["categoria"], "tipo": l["tipo"], "variacoes": variacoes.get(l["id"], [])}
        for l in linhas
    ]
    return {"quantidade": len(produtos), "ha_mais_resultados": ha_mais, "produtos": produtos}


@ferramenta(
    nome="consultar_estoque",
    descricao=(
        "Consulta a quantidade em estoque de UM produto, por loja e por variação (cor/tamanho). "
        "Sem loja_id, devolve todas as lojas. Estoque zero não é erro: significa produto em falta. "
        "Use buscar_produtos antes para obter o produto_id."
    ),
    parametros={
        "produto_id": {"tipo": "integer", "obrigatorio": True, "descricao": "Identificador do produto, obtido em buscar_produtos."},
        "loja_id": {"tipo": "integer", "obrigatorio": False," descricao": "Opcional. Restringe a consulta a uma loja."},
    },
)
def consultar_estoque(ctx, produto_id, loja_id=None):
    produto_id = exigir_inteiro(produto_id, "produto_id")
    if loja_id is not None:
        loja_id = exigir_inteiro(loja_id, "loja_id")

    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, nome, preco, ativo FROM produto WHERE id = %s", (produto_id,))
        produto = cur.fetchone()
        if produto is None:
            raise ErroFerramenta("PRODUTO_NAO_ENCONTRADO", f"Não existe produto com id {produto_id}.")
        if not produto["ativo"]:
            raise ErroFerramenta("PRODUTO_INDISPONIVEL", f"O produto '{produto['nome']}' não está mais a venda.")

        if loja_id is None:
            cur.execute("SELECT id, nome_fantasia, bairro FROM loja ORDER BY id")
        else:
            cur.execute("SELECT id, nome_fantasia, bairro FROM loja WHERE id = %s", (loja_id,))
        lojas = cur.fetchall()
        if loja_id is not None and not lojas:
            raise ErroFerramenta("LOJA_NAO_ENCONTRADA", f"Não existe loja com id {loja_id}.")

        cur.execute(
            "SELECT loja_id, cor, tamanho, quantidade FROM item_estoque "
            "WHERE produto_id = %s ORDER BY loja_id, cor, tamanho", (produto_id,))
        por_loja = {}
        for linha in cur.fetchall():
            por_loja.setdefault(linha["loja_id"], []).append(linha)
    finally:
        cur.close()

    resultado_lojas, total = [], 0
    for loja in lojas:                      # toda loja consultada aparece, mesmo com estoque zero
        itens = por_loja.get(loja["id"], [])
        quantidade = sum(i["quantidade"] for i in itens)
        total += quantidade
        resultado_lojas.append({
            "loja_id": loja["id"], "loja": loja["nome_fantasia"], "bairro": loja["bairro"],
            "quantidade_total": quantidade, "em_falta": quantidade == 0,
            "variacoes": [{"cor": i["cor"], "tamanho": i["tamanho"], "quantidade": i["quantidade"]} for i in itens],
        })
    return {
        "produto": {"id": produto["id"], "nome": produto["nome"], "preco": dinheiro(produto["preco"])},
        "total_disponivel": total,
        "em_falta_em_todas_as_consultadas": total == 0,
        "lojas": resultado_lojas,
    }


@ferramenta(    
    nome="listar_categorias",
    descricao=(
        "Lista as categorias e os tipos do catálogo, com a quantidade de produtos ATIVOS em cada um. "
        "Use para descobrir o que a loja vende ou para sugerir como refinar uma busca."
    ),
    parametros={},
)
def listar_categorias(ctx):
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT c.id, c.nome, COUNT(p.id) AS produtos FROM categoria c "
            "LEFT JOIN produto p ON p.categoria_id = c.id AND p.ativo = 1 "
            "GROUP BY c.id, c.nome ORDER BY c.nome"
        )
        categorias = cur.fetchall()
        cur.execute(
             "SELECT t.id, t.nome, COUNT(p.id) AS produtos FROM tipo t "
            "LEFT JOIN produto p ON p.tipo_id = t.id AND p.ativo = 1 "
            "GROUP BY t.id, t.nome ORDER BY t.nome"           
        )
        tipos = cur.fetchall()
    finally:
        cur.close()
    return {
        "categorias": [{"id": c["id"], "nome": c["nome"], "produtos_ativos": c["produtos"]} for c in categorias],
        "tipos": [{"id": t["id"], "nome": t["nome"], "produtos_ativos": t["produtos"]} for t in tipos],
    }