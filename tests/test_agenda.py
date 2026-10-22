from datetime import date, datetime, timedelta

import pytest

from app.tools import executar


def dia_da_semana(iso_weekday, a_partir_de_dias):
    """Primeira data com o dia da semana pedido (1=segunda ... 7=domingo), a partir de N dias."""
    d = date.today() + timedelta(days=a_partir_de_dias)
    return d + timedelta(days=(iso_weekday - d.isoweekday()) % 7)


def horarios(ctx, data, **extra):
    r = executar("consultar_horarios_disponiveis", {"data": data.isoformat(), **extra}, ctx)
    assert r["ok"], r
    return r["dados"]


def vet_por_especialidade(ctx, esp):
    r = executar("listar_veterinarios", {"especialidade": esp}, ctx)["dados"]["veterinarios"]
    assert len(r) == 1, f"esperava 1 veterinario de {esp}"
    return r[0]


# ------------------------------------------------------------ listar_veterinarios
def test_lista_os_8_veterinarios_com_atendimento(ctx):
    d = executar("listar_veterinarios", {}, ctx)["dados"]
    assert d["quantidade"] == 8
    assert all({"veterinario_id", "nome", "crmv", "especialidade", "loja", "atendimento"} <= set(v)
               for v in d["veterinarios"])


def test_filtros_de_veterinarios(ctx):
    assert executar("listar_veterinarios", {"especialidade": "felinos"}, ctx)["dados"]["quantidade"] == 1
    assert executar("listar_veterinarios", {"especialidade": "CLINICA geral"}, ctx)["dados"]["quantidade"] == 2
    assert executar("listar_veterinarios", {"loja_id": 1}, ctx)["dados"]["quantidade"] == 2
    assert executar("listar_veterinarios", {"especialidade": "%"}, ctx)["dados"]["quantidade"] == 0


def test_dias_e_janelas_de_atendimento_formatados(ctx):
    cardio = vet_por_especialidade(ctx, "cardiologia")
    assert [(a["dia"], a["janelas"]) for a in cardio["atendimento"]] == [
        (dia, ["13:00-17:00"]) for dia in ("segunda", "terça", "quarta", "quinta", "sexta")]


def test_listar_veterinarios_parametros_invalidos(ctx):
    for args in ({"loja_id": "abc"}, {"loja_id": 0}, {"especialidade": ""}, {"especialidade": 7}, {"nome": "x"}):
        r = executar("listar_veterinarios", args, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", args


# ------------------------------------------------- consultar_horarios_disponiveis
def test_dia_sem_agendamentos_mostra_todos_os_horarios_da_janela(ctx):
    segunda = dia_da_semana(1, 50)                    # alem dos 30 dias com agendamentos de exemplo
    d = horarios(ctx, segunda, especialidade="cardiologia")
    assert d["dia_semana"] == "segunda" and d["duracao_minutos"] == 30
    assert d["veterinarios"][0]["horarios_livres"] == [
        "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30"]
    assert d["total_horarios_livres"] == 8


def test_sabado_so_tem_quem_atende_no_sabado(ctx):
    d = horarios(ctx, dia_da_semana(6, 50), especialidade="dermatologia")
    assert d["veterinarios"][0]["horarios_livres"] == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]
    assert horarios(ctx, dia_da_semana(6, 50), especialidade="cardiologia")["veterinarios"] == []


def test_domingo_ninguem_atende(ctx):
    d = horarios(ctx, dia_da_semana(7, 50))
    assert d["veterinarios"] == [] and d["total_horarios_livres"] == 0


def test_horario_ocupado_some_e_horario_cancelado_continua_livre(ctx):
    segunda = dia_da_semana(1, 50)
    cardio = vet_por_especialidade(ctx, "cardiologia")["veterinario_id"]
    cur = ctx.conn.cursor()
    cur.execute("SELECT cliente_id, animal_id FROM perfil_pet LIMIT 1")
    cliente, animal = cur.fetchone()
    inserir = ("INSERT INTO agendamento (cliente_id, animal_id, veterinario_id, tipo, data_hora, status) "
               "VALUES (%s, %s, %s, 'consulta', %s, %s)")
    try:
        cur.execute(inserir, (cliente, animal, cardio, f"{segunda} 14:00:00", "confirmado"))
        cur.execute(inserir, (cliente, animal, cardio, f"{segunda} 14:30:00", "cancelado"))
        livres = horarios(ctx, segunda, veterinario_id=cardio)["veterinarios"][0]["horarios_livres"]
        assert "14:00" not in livres            # ocupado por agendamento ativo
        assert "14:30" in livres                # cancelado libera o horario
        assert len(livres) == 7
    finally:
        ctx.conn.rollback()                     # nao deixa nada gravado
        cur.close()


def test_hoje_so_mostra_horarios_com_1_hora_de_antecedencia(ctx, monkeypatch):
    segunda = dia_da_semana(1, 50)
    monkeypatch.setattr("app.tools.agenda._agora", lambda: datetime(segunda.year, segunda.month, segunda.day, 14, 10))
    livres = horarios(ctx, segunda, especialidade="cardiologia")["veterinarios"][0]["horarios_livres"]
    assert livres == ["15:30", "16:00", "16:30"]          # 14:10 + 1h = 15:10 -> primeiro horario cheio: 15:30


def test_limites_de_data(ctx, monkeypatch):
    monkeypatch.setattr("app.tools.agenda._agora", lambda: datetime(2030, 1, 15, 10, 0))
    passado = executar("consultar_horarios_disponiveis", {"data": "2030-01-14"}, ctx)
    longe = executar("consultar_horarios_disponiveis", {"data": "2030-03-17"}, ctx)      # 61 dias
    limite = executar("consultar_horarios_disponiveis", {"data": "2030-03-16"}, ctx)     # 60 dias
    assert passado["erro"]["codigo"] == "PARAMETRO_INVALIDO" and "passado" in passado["erro"]["mensagem"]
    assert longe["erro"]["codigo"] == "PARAMETRO_INVALIDO" and "60" in longe["erro"]["mensagem"]
    assert limite["ok"]


def test_datas_mal_formatadas_sao_rejeitadas(ctx):
    for valor in ("20/10/2026", "2026-13-01", "2026-02-30", "2026-1-5", "amanha", "", 20261020, None, ["2026-10-20"]):
        r = executar("consultar_horarios_disponiveis", {"data": valor}, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", valor


def test_veterinario_inexistente_e_combinacao_sem_resultado(ctx):
    data = dia_da_semana(1, 50).isoformat()
    r = executar("consultar_horarios_disponiveis", {"data": data, "veterinario_id": 999}, ctx)
    assert r["erro"]["codigo"] == "VETERINARIO_NAO_ENCONTRADO"
    cardio = vet_por_especialidade(ctx, "cardiologia")["veterinario_id"]
    r = executar("consultar_horarios_disponiveis",
                 {"data": data, "veterinario_id": cardio, "especialidade": "dermatologia"}, ctx)
    assert r["ok"] and r["dados"]["veterinarios"] == []      # filtros que nao combinam: vazio, nao erro


def test_parametros_invalidos_na_consulta_de_horarios(ctx):
    data = dia_da_semana(1, 50).isoformat()
    for extra in ({"veterinario_id": "abc"}, {"veterinario_id": 0}, {"especialidade": ""}, {"sql": "x"}):
        r = executar("consultar_horarios_disponiveis", {"data": data, **extra}, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO", extra
    assert not executar("consultar_horarios_disponiveis", {}, ctx)["ok"]