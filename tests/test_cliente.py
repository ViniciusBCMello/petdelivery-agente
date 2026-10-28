import json
from datetime import datetime

import pytest

from app.tools import REGISTRO, executar

FERRAMENTAS_PESSOAIS = ["consultar_meu_perfil", "listar_meus_pets", "listar_meus_enderecos",
                        "listar_meus_agendamentos", "listar_meus_pedidos"]


def sql(ctx, consulta, params=()):
    cur = ctx.conn.cursor()
    cur.execute(consulta, params)
    linhas = cur.fetchall()
    cur.close()
    return linhas


def cliente_com_mais_agendamentos(ctx):
    return sql(ctx, "SELECT cliente_id FROM agendamento GROUP BY cliente_id "
                    "ORDER BY COUNT(*) DESC, cliente_id LIMIT 1")[0][0]


# =============================================== identidade: o ponto mais importante
@pytest.mark.parametrize("nome", FERRAMENTAS_PESSOAIS)
def test_sem_login_nenhuma_ferramenta_pessoal_responde(ctx, nome):
    r = executar(nome, {}, ctx)                      # ctx.cliente_id e None
    assert not r["ok"] and r["erro"]["codigo"] == "NAO_AUTENTICADO"


def test_consultar_pedido_tambem_exige_login(ctx):
    assert executar("consultar_pedido", {"pedido_id": 1}, ctx)["erro"]["codigo"] == "NAO_AUTENTICADO"


def test_identidade_invalida_na_sessao_e_recusada(como_cliente):
    for cid in (0, -1, True, "1", None, 1.5):
        r = executar("listar_meus_pets", {}, como_cliente(cid))
        assert r["erro"]["codigo"] == "NAO_AUTENTICADO", cid


def test_modelo_nao_consegue_escolher_o_cliente(como_cliente):
    for nome in FERRAMENTAS_PESSOAIS:
        r = executar(nome, {"cliente_id": 2}, como_cliente(1))
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", nome
    r = executar("consultar_pedido", {"pedido_id": 1, "cliente_id": 2}, como_cliente(1))
    assert r["erro"]["codigo"] == "PARAMETRO_INVALIDO"


def test_nenhuma_ferramenta_pessoal_declara_parametro_de_cliente():
    for nome in FERRAMENTAS_PESSOAIS + ["consultar_pedido"]:
        assert not any("cliente" in p for p in REGISTRO[nome].parametros), nome


# ======================================================================== perfil
def test_perfil_do_cliente_logado(ctx, como_cliente):
    for cid in range(1, 9):                      # varios clientes: cada um ve so o proprio perfil
        esperado = sql(ctx, "SELECT nome, email, telefone FROM cliente WHERE id = %s", (cid,))[0]
        d = executar("consultar_meu_perfil", {}, como_cliente(cid))["dados"]
        assert (d["nome"], d["email"], d["telefone"]) == esperado and d["cliente_desde"], cid


def test_perfil_nao_expoe_cpf(ctx, como_cliente):
    cid, cpf = sql(ctx, "SELECT id, cpf FROM cliente WHERE cpf IS NOT NULL LIMIT 1")[0]
    texto = json.dumps(executar("consultar_meu_perfil", {}, como_cliente(cid)))
    assert "cpf" not in texto.lower() and cpf not in texto


def test_perfil_de_cliente_inexistente(como_cliente):
    assert executar("consultar_meu_perfil", {}, como_cliente(999999))["erro"]["codigo"] == "CLIENTE_NAO_ENCONTRADO"


# ========================================================================== pets
def test_pets_sao_exatamente_os_do_cliente(ctx, como_cliente):
    for cid in range(1, 11):
        esperado = {r[0] for r in sql(ctx, "SELECT animal_id FROM perfil_pet WHERE cliente_id = %s", (cid,))}
        d = executar("listar_meus_pets", {}, como_cliente(cid))["dados"]
        assert {p["animal_id"] for p in d["pets"]} == esperado and d["quantidade"] == len(esperado), cid


def test_pet_traz_os_dados_esperados(ctx, como_cliente):
    pet = executar("listar_meus_pets", {}, como_cliente(1))["dados"]["pets"][0]
    assert {"animal_id", "nome", "especie", "raca", "idade_anos", "peso_kg"} == set(pet)
    assert pet["peso_kg"] is None or isinstance(pet["peso_kg"], float)


def test_cliente_sem_cadastro_nao_ve_pets_de_ninguem(como_cliente):
    assert executar("listar_meus_pets", {}, como_cliente(999999))["dados"]["quantidade"] == 0


# ==================================================================== enderecos
def test_enderecos_sao_exatamente_os_do_cliente(ctx, como_cliente):
    for cid in range(1, 11):
        esperado = {r[0] for r in sql(ctx, "SELECT id FROM endereco WHERE cliente_id = %s", (cid,))}
        d = executar("listar_meus_enderecos", {}, como_cliente(cid))["dados"]
        assert {e["endereco_id"] for e in d["enderecos"]} == esperado, cid


def test_endereco_nao_expoe_coordenadas(como_cliente):
    e = executar("listar_meus_enderecos", {}, como_cliente(1))["dados"]["enderecos"][0]
    assert {"endereco_id", "endereco", "bairro", "cep", "cidade", "estado"} == set(e)


# ================================================================== agendamentos
def test_futuros_so_trazem_agendamentos_ativos_e_futuros(ctx, como_cliente):
    cid = cliente_com_mais_agendamentos(ctx)
    d = executar("listar_meus_agendamentos", {}, como_cliente(cid))["dados"]
    assert d["periodo"] == "futuros"
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    assert all(a["status"] in ("agendado", "confirmado") and a["data_hora"] >= agora for a in d["agendamentos"])
    datas = [a["data_hora"] for a in d["agendamentos"]]
    assert datas == sorted(datas)                                   # mais proximo primeiro


def test_passados_e_todos(ctx, como_cliente):
    cid = cliente_com_mais_agendamentos(ctx)
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    passados = executar("listar_meus_agendamentos", {"periodo": "passados"}, como_cliente(cid))["dados"]
    assert all(a["data_hora"] < agora for a in passados["agendamentos"])
    datas = [a["data_hora"] for a in passados["agendamentos"]]
    assert datas == sorted(datas, reverse=True)                     # mais recente primeiro
    todos = executar("listar_meus_agendamentos", {"periodo": "TODOS"}, como_cliente(cid))["dados"]
    total = sql(ctx, "SELECT COUNT(*) FROM agendamento WHERE cliente_id = %s", (cid,))[0][0]
    assert todos["quantidade"] == min(total, 20)


def test_agendamentos_resultado_exato_com_hora_fixa(ctx, como_cliente, monkeypatch):
    fixa = datetime.now().replace(microsecond=0)
    monkeypatch.setattr("app.tools.cliente._agora", lambda: fixa)
    cid = cliente_com_mais_agendamentos(ctx)
    esperado = [r[0] for r in sql(
        ctx, "SELECT id FROM agendamento WHERE cliente_id = %s AND data_hora >= %s "
             "AND status IN ('agendado','confirmado') ORDER BY data_hora, id", (cid, fixa))]
    d = executar("listar_meus_agendamentos", {}, como_cliente(cid))["dados"]
    assert [a["agendamento_id"] for a in d["agendamentos"]] == esperado[:20]


def test_agendamentos_sao_todos_do_proprio_cliente(ctx, como_cliente):
    for cid in range(1, 16):
        d = executar("listar_meus_agendamentos", {"periodo": "todos"}, como_cliente(cid))["dados"]
        ids = [a["agendamento_id"] for a in d["agendamentos"]]
        if ids:
            marcadores = ", ".join(["%s"] * len(ids))
            donos = {r[0] for r in sql(ctx, f"SELECT DISTINCT cliente_id FROM agendamento WHERE id IN ({marcadores})", ids)}
            assert donos == {cid}, cid


def test_periodo_invalido(como_cliente):
    for periodo in ("amanha", "", 7, ["futuros"]):
        r = executar("listar_meus_agendamentos", {"periodo": periodo}, como_cliente(1))
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", periodo


def test_futuros_nao_inclui_cancelado_mas_todos_inclui(ctx, como_cliente):
    cid, animal = sql(ctx, "SELECT cliente_id, animal_id FROM perfil_pet ORDER BY id LIMIT 1")[0]
    vet = sql(ctx, "SELECT id FROM veterinario ORDER BY id LIMIT 1")[0][0]
    inserir = ("INSERT INTO agendamento (cliente_id, animal_id, veterinario_id, tipo, data_hora, status) "
               "VALUES (%s, %s, %s, 'consulta', %s, %s)")
    cur = ctx.conn.cursor()
    try:
        cur.execute(inserir, (cid, animal, vet, datetime(2099, 1, 4, 10, 0), "cancelado"))
        cancelado = cur.lastrowid
        cur.execute(inserir, (cid, animal, vet, datetime(2099, 1, 4, 10, 30), "agendado"))
        ativo = cur.lastrowid
        futuros = {a["agendamento_id"] for a in
                   executar("listar_meus_agendamentos", {}, como_cliente(cid))["dados"]["agendamentos"]}
        todos = {a["agendamento_id"] for a in
                 executar("listar_meus_agendamentos", {"periodo": "todos"}, como_cliente(cid))["dados"]["agendamentos"]}
        assert ativo in futuros and cancelado not in futuros       # cancelado nao e "proximo agendamento"
        assert {ativo, cancelado} <= todos                         # mas continua no historico completo
    finally:
        ctx.conn.rollback()                                        # nao deixa nada gravado
        cur.close()