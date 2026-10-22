from .base import ErroFerramenta, escapar_like, exigir_inteiro, exigir_texto, ferramenta
from .geo import distancia_km

MAX_LOJAS_PROXIMAS = 5


@ferramenta(
    nome="listar_lojas",
    descricao="Lista as lojas da rede com endereço, bairro e cidade. Pode filtrar por bairro.",
    parametros={
        "bairro": {"tipo": "string", "obrigatorio": False, "descricao": "Opcional. Mostrar só as lojas cujo bairro contenha este texto."},
    },
)
def listar_lojas(ctx, bairro=None):
    sql = "SELECT id, nome_fantasia, endereco, bairro, cidade, estado FROM loja"
    params = []
    if bairro is not None:
        bairro = exigir_texto(bairro, "bairro", max_len=100)
        sql += " WHERE bairro LIKE %s"
        params.append(f"%{escapar_like(bairro)}%")
    sql += " ORDER BY nome_fantasia"

    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        lojas = cur.fetchall()
    finally:
        cur.close()
    return {
        "quantidade": len(lojas),
        "lojas": [{"loja_id": l["id"], "loja": l["nome_fantasia"], "endereco": l["endereco"],
                   "bairro": l["bairro"], "cidade": l["cidade"], "estado": l["estado"]} for l in lojas],        
    }


@ferramenta(
    nome="lojas_proximas",
    descricao=(
        "Ordena as lojas pela distância em LINHA RETA até um bairro."
        "Se o produto_id for informado, mostra o estoque do produto em cada loja e indica a loja mais próxima que TEM o produto."
        "Bairro desconhecido devolve erro com a lista de bairros conhecidos."
    ),
    parametros={
        "bairro": {"tipo": "string", "obrigatorio":True, "descricao":"Bairro de referencia, por exemplo: 'Tijuca'."},
        "produto_id": {"tipo": "integer", "obrigatorio": False, "descricao": "Opcional. Produto cujo estoque deve ser considerado (obtido em buscar_produtos)."}
    },
)
def lojas_proximas(ctx, bairro, produto_id=None):
    bairro = exigir_texto(bairro, "bairro", max_len=100)
    if produto_id is not None:
        produto_id = exigir_inteiro(produto_id, "produto_id")

    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome, cidade, estado, latitude, longitude FROM bairro "
                    "WHERE nome = %s ORDER BY cidade LIMIT 1", (bairro,))
        ref = cur.fetchone()
        if ref is None:
            cur.execute("SELECT nome FROM bairro ORDER BY nome")
            conhecidos = ", ".join(r["nome"] for r in cur.fetchall())
            raise ErroFerramenta("BAIRRO_NAO_ENCONTRADO",
                                 f"Não conheço o bairro '{bairro}'. Bairros conhecidos: {conhecidos}.")

        produto, estoque = None, {}
        if produto_id is not None:
            cur.execute("SELECT id, nome, ativo FROM produto WHERE id = %s", (produto_id,))
            produto = cur.fetchone()
            if produto is None:
                raise ErroFerramenta("PRODUTO_NAO_ENCONTRADO", f"Não existe produto com id {produto_id}.")
            if not produto["ativo"]:
                raise ErroFerramenta("PRODUTO_INDISPONIVEL", f"O produto '{produto['nome']}' não está mais a venda.")
            cur.execute("SELECT loja_id, SUM(quantidade) AS q FROM item_estoque "
                        "WHERE produto_id = %s GROUP BY loja_id", (produto_id,))
            estoque = {r["loja_id"]: int(r["q"]) for r in cur.fetchall()}

        cur.execute("SELECT id, nome_fantasia, endereco, bairro, latitude, longitude FROM loja "
                    "WHERE latitude IS NOT NULL AND longitude IS NOT NULL")
        lojas = cur.fetchall()
    finally:
        cur.close()

    lat0, lon0 = float(ref["latitude"]), float(ref["longitude"])
    ordenadas = []
    for loja in lojas:
        d = distancia_km(lat0, lon0, float(loja["latitude"]), float(loja["longitude"]))
        item = {"loja_id": loja["id"], "loja": loja["nome_fantasia"], "bairro": loja["bairro"],
                "endereco": loja["endereco"], "distancia_km": round(d, 1)}
        if produto is not None:
            quantidade = estoque.get(loja["id"],0)
            item["quantidade_produto"] = quantidade
            item["tem_estoque"] = quantidade > 0
        ordenadas.append((d, item))
    ordenadas.sort(key=lambda par: (par[0],par[1]["loja"]))
    itens = [item for _, item in ordenadas]

    # Calculada sobre TODAS as lojas: a mais proxima com estoque pode nao estar entre as 5 primeiras.
    com_estoque = next((i for i in itens if i.get("tem_estoque")), None) if produto is not None else None
    return {
        "referencia": {"bairro": ref["nome"], "cidade": ref["cidade"], "estado": ref["estado"]},
        "produto": None if produto is None else {"id": produto["id"], "nome": produto["nome"]},
        "lojas": itens[:MAX_LOJAS_PROXIMAS],
        "mais_proxima_com_estoque": com_estoque,
    }    