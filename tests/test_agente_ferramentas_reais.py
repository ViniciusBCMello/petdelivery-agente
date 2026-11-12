"""O agente (com um LLM de mentira) usando as ferramentas REAIS e o banco de verdade.
O ponto: o cliente e as regras de segurança vêm da APLICAÇÃO, não do que o modelo pede."""
import json

from test_falsos import ProvedorFalso, chama, texto

from app.agente.orquestrador import Agente
from app.tools import executar


def rodar(ctx, roteiro, mensagem="x"):
    prov = ProvedorFalso(roteiro)
    resultado = Agente(prov).responder([], mensagem, ctx)
    envios = [json.loads(e.conteudo) for lote in prov.envios for e in lote]
    return resultado, envios


def sql(ctx, consulta, params=()):
    cur = ctx.conn.cursor()
    cur.execute(consulta, params)
    linhas = cur.fetchall()
    cur.close()
    return linhas


def test_busca_real_de_produto_chega_ao_modelo(ctx):
    r, envios = rodar(ctx, [chama(("c1", "buscar_produtos", '{"termo": "racao"}')), texto("Temos opções.")])
    assert envios[0]["ok"] and envios[0]["dados"]["produtos"]
    assert r.resposta == "Temos opções." and r.chamadas[0].ok


def test_ids_pedidos_pelo_modelo_sao_validados_pelo_banco(ctx):
    r, envios = rodar(ctx, [chama(("c1", "consultar_estoque", '{"produto_id": 999999}')), texto("Não achei.")])
    assert envios[0]["erro"]["codigo"] == "PRODUTO_NAO_ENCONTRADO"
    assert r.chamadas[0].codigo_erro == "PRODUTO_NAO_ENCONTRADO"


def test_modelo_nao_consegue_escolher_o_cliente(como_cliente):
    # O modelo tenta passar cliente_id (como se quisesse ver os pets de outra pessoa).
    r, envios = rodar(como_cliente(1), [chama(("c1", "listar_meus_pets", '{"cliente_id": 2}')), texto("Não consegui.")])
    assert envios[0]["ok"] is False and envios[0]["erro"]["codigo"] == "PARAMETRO_INVALIDO"
    assert "cliente_id" in envios[0]["erro"]["mensagem"]


def test_ferramentas_pessoais_usam_o_cliente_do_contexto(ctx, como_cliente):
    donos = [r[0] for r in sql(ctx, "SELECT cliente_id FROM perfil_pet GROUP BY cliente_id ORDER BY cliente_id LIMIT 2")]
    for dono in donos:
        _, envios = rodar(como_cliente(dono), [chama(("c", "listar_meus_pets", "{}")), texto("ok")])
        assert envios[0] == executar("listar_meus_pets", {}, como_cliente(dono))       # os pets dele, e só dele


def test_sem_login_as_ferramentas_pessoais_recusam(ctx):
    r, envios = rodar(ctx, [chama(("c", "consultar_meu_perfil", "{}")), texto("Faça login.")])      # ctx sem cliente
    assert envios[0]["erro"]["codigo"] == "NAO_AUTENTICADO" and r.chamadas[0].ok is False


def test_pedido_de_outro_cliente_e_igual_a_pedido_inexistente(ctx, como_cliente):
    a, b = [r[0] for r in sql(ctx, "SELECT cliente_id FROM pedido GROUP BY cliente_id ORDER BY COUNT(*) DESC, cliente_id LIMIT 2")]
    pedido_de_b = sql(ctx, "SELECT id FROM pedido WHERE cliente_id = %s LIMIT 1", (b,))[0][0]

    _, alheio = rodar(como_cliente(a), [chama(("c", "consultar_pedido", json.dumps({"pedido_id": pedido_de_b}))), texto("x")])
    _, inexistente = rodar(como_cliente(a), [chama(("c", "consultar_pedido", '{"pedido_id": 999999}')), texto("x")])
    assert alheio[0]["erro"]["codigo"] == "PEDIDO_NAO_ENCONTRADO"
    assert alheio[0] == inexistente[0]                          # o modelo não descobre que o pedido existe


def test_cpf_nunca_chega_ao_modelo(ctx, como_cliente):
    cpf = sql(ctx, "SELECT cpf FROM cliente WHERE id = 1")[0][0]
    r, envios = rodar(como_cliente(1), [chama(("a", "consultar_meu_perfil", "{}"), ("b", "listar_meus_pedidos", "{}")), texto("ok")])
    assert cpf and all(cpf not in json.dumps(e) for e in envios)


def test_argumentos_quebrados_nao_chegam_ao_banco(ctx):
    r, envios = rodar(ctx, [chama(("c", "buscar_produtos", '{"termo": "racao"; DROP TABLE produto')), texto("Erro.")])
    assert envios[0]["erro"]["codigo"] == "PARAMETRO_INVALIDO"
    assert sql(ctx, "SELECT COUNT(*) FROM produto")[0][0] > 0       # a tabela continua lá