from app.tools import executar


# ----------------------------------------------------------------- buscar_produtos
def test_busca_por_palavra_devolve_produtos_ativos(ctx):
    r = executar("buscar_produtos", {"termo": "racao"}, ctx)
    assert r["ok"] and r["dados"]["quantidade"] > 0
    campos = {"id", "nome", "preco", "categoria", "tipo", "variacoes"}
    assert all(campos <= set(p) for p in r["dados"]["produtos"])


def test_busca_ignora_acento_e_maiuscula(ctx):
    sem = executar("buscar_produtos", {"termo": "racao"}, ctx)["dados"]["produtos"]
    com = executar("buscar_produtos", {"termo": "RAÇÃO"}, ctx)["dados"]["produtos"]
    assert [p["id"] for p in sem] == [p["id"] for p in com] and sem


def test_busca_com_varias_palavras_restringe(ctx):
    todas = executar("buscar_produtos", {"termo": "racao"}, ctx)["dados"]["produtos"]
    so_gatos = executar("buscar_produtos", {"termo": "racao gatos"}, ctx)["dados"]["produtos"]
    assert 0 < len(so_gatos) < len(todas)
    assert all("Gatos" in p["nome"] for p in so_gatos)


def test_busca_sem_resultado_nao_e_erro(ctx):
    r = executar("buscar_produtos", {"termo": "zzzzxxxx"}, ctx)
    assert r["ok"] and r["dados"]["quantidade"] == 0 and r["dados"]["produtos"] == []


def test_produto_inativo_nao_aparece_na_busca(ctx):
    r = executar("buscar_produtos", {"termo": "Arranhador Torre"}, ctx)
    assert r["ok"] and r["dados"]["quantidade"] == 0


def test_busca_limita_a_10_resultados(ctx):
    r = executar("buscar_produtos", {"termo": "a"}, ctx)
    assert r["dados"]["quantidade"] == 10 and r["dados"]["ha_mais_resultados"] is True


def test_preco_vem_como_texto_com_duas_casas(ctx):
    r = executar("buscar_produtos", {"termo": "Royal Canin"}, ctx)
    assert r["dados"]["produtos"][0]["preco"] == "51.82"


def test_percentual_e_sublinhado_valem_como_letras_comuns(ctx):
    # sem escapar, '%' casaria com TUDO
    assert executar("buscar_produtos", {"termo": "%"}, ctx)["dados"]["quantidade"] == 0
    assert executar("buscar_produtos", {"termo": "_"}, ctx)["dados"]["quantidade"] == 0


def test_tentativa_de_sql_injection_e_inofensiva(ctx):
    antes = ctx.conn.cursor()
    antes.execute("SELECT COUNT(*) FROM produto")
    total = antes.fetchone()[0]
    antes.close()
    r = executar("buscar_produtos", {"termo": "'; DROP TABLE produto; --"}, ctx)
    assert r["ok"] and r["dados"]["quantidade"] == 0
    depois = ctx.conn.cursor()
    depois.execute("SELECT COUNT(*) FROM produto")
    assert depois.fetchone()[0] == total
    depois.close()


def test_termo_vazio_ou_enorme_e_rejeitado(ctx):
    for termo in ("", "   ", "x" * 81):
        r = executar("buscar_produtos", {"termo": termo}, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO"


def test_termo_com_tipo_errado_e_rejeitado(ctx):
    for termo in (123, ["racao"], {"a": 1}, True):
        r = executar("buscar_produtos", {"termo": termo}, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO"


# --------------------------------------------------------------- consultar_estoque
def test_estoque_normal_lista_todas_as_lojas(ctx, achar_produto):
    pid = achar_produto("Royal Canin")
    d = executar("consultar_estoque", {"produto_id": pid}, ctx)["dados"]
    assert len(d["lojas"]) == 6 and d["produto"]["nome"] == "Royal Canin"
    assert d["total_disponivel"] == sum(l["quantidade_total"] for l in d["lojas"])


def test_produto_em_falta_em_todas_as_lojas(ctx, achar_produto):
    pid = achar_produto("Nutrimax Gatos Filhotes")
    r = executar("consultar_estoque", {"produto_id": pid}, ctx)
    assert r["ok"]                                        # estoque zero NÃO é erro
    assert r["dados"]["total_disponivel"] == 0
    assert r["dados"]["em_falta_em_todas_as_consultadas"] is True
    assert all(l["em_falta"] for l in r["dados"]["lojas"])


def test_produto_so_em_uma_loja(ctx, achar_produto):
    pid = achar_produto("Focinho Feliz Premium Gatos")
    lojas = executar("consultar_estoque", {"produto_id": pid}, ctx)["dados"]["lojas"]
    com_estoque = [l for l in lojas if not l["em_falta"]]
    assert len(com_estoque) == 1 and com_estoque[0]["quantidade_total"] == 12


def test_filtro_por_loja(ctx, achar_produto):
    pid = achar_produto("Royal Canin")
    d = executar("consultar_estoque", {"produto_id": pid, "loja_id": 2}, ctx)["dados"]
    assert [l["loja_id"] for l in d["lojas"]] == [2]


def test_variacoes_aparecem_no_estoque(ctx, achar_produto):
    pid = achar_produto("Coleira de Nylon")
    loja = executar("consultar_estoque", {"produto_id": pid, "loja_id": 1}, ctx)["dados"]["lojas"][0]
    assert {(v["cor"], v["tamanho"]) for v in loja["variacoes"]} == {
        ("azul", "P"), ("azul", "M"), ("vermelho", "P"), ("vermelho", "M")}


def test_erros_de_negocio_tem_codigo_proprio(ctx, achar_produto):
    r = executar("consultar_estoque", {"produto_id": 999999}, ctx)
    assert r["erro"]["codigo"] == "PRODUTO_NAO_ENCONTRADO"
    r = executar("consultar_estoque", {"produto_id": achar_produto("Royal Canin"), "loja_id": 999}, ctx)
    assert r["erro"]["codigo"] == "LOJA_NAO_ENCONTRADA"


def test_produto_inativo_nao_pode_ter_estoque_consultado(ctx):
    cur = ctx.conn.cursor()
    cur.execute("SELECT id FROM produto WHERE ativo = 0 LIMIT 1")
    inativo = cur.fetchone()[0]
    cur.close()
    assert executar("consultar_estoque", {"produto_id": inativo}, ctx)["erro"]["codigo"] == "PRODUTO_INDISPONIVEL"


def test_ids_invalidos_sao_rejeitados(ctx):
    for valor in ("abc", 0, -3, 1.5, True, [1], None):
        r = executar("consultar_estoque", {"produto_id": valor}, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", valor


def test_numero_em_texto_e_aceito(ctx, achar_produto):
    pid = achar_produto("Royal Canin")
    assert executar("consultar_estoque", {"produto_id": str(pid)}, ctx)["ok"]


# ------------------------------------------------------------------ listar_categorias
def test_categorias_e_tipos_com_contagem_de_ativos(ctx):
    d = executar("listar_categorias", {}, ctx)["dados"]
    nomes = {c["nome"] for c in d["categorias"]}
    assert {"Ração", "Medicamentos", "Higiene", "Acessórios", "Brinquedos"} <= nomes
    assert all(c["produtos_ativos"] >= 0 for c in d["categorias"] + d["tipos"])
    # a soma por categoria bate com o total de produtos ativos (cada produto tem 1 categoria)
    cur = ctx.conn.cursor()
    cur.execute("SELECT COUNT(*) FROM produto WHERE ativo = 1")
    total_ativos = cur.fetchone()[0]
    cur.close()
    assert sum(c["produtos_ativos"] for c in d["categorias"]) == total_ativos
    assert sum(t["produtos_ativos"] for t in d["tipos"]) == total_ativos


def test_listar_categorias_rejeita_parametros_inventados(ctx):
    r = executar("listar_categorias", {"filtro": "x"}, ctx)
    assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO"