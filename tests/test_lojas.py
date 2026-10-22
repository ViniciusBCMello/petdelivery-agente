from app.tools import executar


# ------------------------------------------------------------------- listar_lojas
def test_lista_todas_as_lojas(ctx):
    d = executar("listar_lojas", {}, ctx)["dados"]
    assert d["quantidade"] == 6
    assert {l["loja"] for l in d["lojas"]} >= {"Tudo Papet", "Dr Pet", "Amigão Pet Shop"}


def test_filtra_lojas_por_bairro_sem_acento(ctx):
    d = executar("listar_lojas", {"bairro": "tijuca"}, ctx)["dados"]
    assert [l["loja"] for l in d["lojas"]] == ["Lily's Pet Shop"]


def test_bairro_sem_loja_nao_e_erro(ctx):
    d = executar("listar_lojas", {"bairro": "Atlantida"}, ctx)["dados"]
    assert d["quantidade"] == 0 and d["lojas"] == []


def test_filtro_trata_percentual_como_letra(ctx):
    assert executar("listar_lojas", {"bairro": "%"}, ctx)["dados"]["quantidade"] == 0


# ----------------------------------------------------------------- lojas_proximas
def test_loja_do_proprio_bairro_vem_primeiro_a_distancia_zero(ctx):
    d = executar("lojas_proximas", {"bairro": "Madureira"}, ctx)["dados"]
    assert d["lojas"][0]["loja"] == "Dr Pet" and d["lojas"][0]["distancia_km"] == 0.0


def test_bairro_sem_acento_e_sem_maiuscula(ctx):
    d = executar("lojas_proximas", {"bairro": "meier"}, ctx)["dados"]
    assert d["referencia"]["bairro"] == "Méier"


def test_lojas_vem_ordenadas_por_distancia_e_limitadas_a_5(ctx):
    d = executar("lojas_proximas", {"bairro": "Tijuca"}, ctx)["dados"]
    distancias = [l["distancia_km"] for l in d["lojas"]]
    assert distancias == sorted(distancias) and len(d["lojas"]) == 5
    assert d["produto"] is None and d["mais_proxima_com_estoque"] is None
    assert all("tem_estoque" not in l for l in d["lojas"])


def test_bairro_sem_loja_usa_o_ponto_do_bairro(ctx):
    d = executar("lojas_proximas", {"bairro": "Bangu"}, ctx)["dados"]   # não tem loja em Bangu
    assert d["lojas"][0]["distancia_km"] > 0


def test_com_produto_mostra_estoque_por_loja(ctx, achar_produto):
    pid = achar_produto("Royal Canin")
    d = executar("lojas_proximas", {"bairro": "Tijuca", "produto_id": pid}, ctx)["dados"]
    assert d["produto"]["nome"] == "Royal Canin"
    assert all({"quantidade_produto", "tem_estoque"} <= set(l) for l in d["lojas"])
    for l in d["lojas"]:
        assert l["tem_estoque"] == (l["quantidade_produto"] > 0)


def test_loja_mais_proxima_com_estoque_pode_estar_fora_das_5_primeiras(ctx, achar_produto):
    # este produto so tem estoque na loja mais distante da rede
    pid = achar_produto("Focinho Feliz Premium Gatos")
    d = executar("lojas_proximas", {"bairro": "Tijuca", "produto_id": pid}, ctx)["dados"]
    assert not any(l["tem_estoque"] for l in d["lojas"])         # nenhuma das 5 primeiras tem
    achada = d["mais_proxima_com_estoque"]
    assert achada is not None and achada["quantidade_produto"] == 12


def test_produto_em_falta_em_todas_nao_tem_loja_com_estoque(ctx, achar_produto):
    pid = achar_produto("Nutrimax Gatos Filhotes")
    d = executar("lojas_proximas", {"bairro": "Tijuca", "produto_id": pid}, ctx)["dados"]
    assert d["mais_proxima_com_estoque"] is None


def test_erros_de_negocio(ctx, achar_produto):
    r = executar("lojas_proximas", {"bairro": "Atlantida"}, ctx)
    assert r["erro"]["codigo"] == "BAIRRO_NAO_ENCONTRADO" and "Tijuca" in r["erro"]["mensagem"]
    r = executar("lojas_proximas", {"bairro": "Tijuca", "produto_id": 999999}, ctx)
    assert r["erro"]["codigo"] == "PRODUTO_NAO_ENCONTRADO"


def test_parametros_invalidos(ctx):
    for args in ({"bairro": ""}, {"bairro": 5}, {"bairro": "Tijuca", "produto_id": "abc"},
                 {"bairro": "Tijuca", "produto_id": 0}):
        r = executar("lojas_proximas", args, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", args


def test_produto_inativo_nao_entra_na_comparacao_de_lojas(ctx):
    cur = ctx.conn.cursor()
    cur.execute("SELECT id FROM produto WHERE ativo = 0 LIMIT 1")
    inativo = cur.fetchone()[0]
    cur.close()
    r = executar("lojas_proximas", {"bairro": "Tijuca", "produto_id": inativo}, ctx)
    assert r["erro"]["codigo"] == "PRODUTO_INDISPONIVEL"