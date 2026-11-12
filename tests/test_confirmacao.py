"""Cofre de códigos de confirmação (sem banco)."""
from datetime import timedelta

import pytest

from app.tools import Contexto, ErroFerramenta
from app.tools.confirmacao import Confirmacoes, conferir, propor
from conftest import Relogio

P = {"animal_id": 1, "hora": "09:30"}


@pytest.fixture()
def cofre():
    relogio = Relogio()
    c = Confirmacoes(agora=relogio, limite=3)
    c.relogio = relogio
    return c


def codigo_do(cofre, turno=1, cliente=7, acao="agendar", params=P):
    return cofre.emitir(cliente, acao, params, turno)


def recusa(cofre, codigo, esperado, cliente=7, acao="agendar", params=P, turno=2):
    with pytest.raises(ErroFerramenta) as e:
        cofre.consumir(codigo, cliente, acao, params, turno)
    assert e.value.codigo == esperado


def test_codigo_vale_em_turno_posterior_e_so_uma_vez(cofre):
    c = codigo_do(cofre)
    cofre.consumir(c, 7, "agendar", P, 2)
    recusa(cofre, c, "CONFIRMACAO_INVALIDA")                  # já foi gasto


def test_no_mesmo_turno_e_prematuro_e_nao_gasta_o_codigo(cofre):
    c = codigo_do(cofre, turno=5)
    recusa(cofre, c, "CONFIRMACAO_PREMATURA", turno=5)        # mesma mensagem do cliente
    recusa(cofre, c, "CONFIRMACAO_PREMATURA", turno=4)        # turno anterior também não vale
    cofre.consumir(c, 7, "agendar", P, 6)                     # na mensagem seguinte funciona


def test_parametros_diferentes_sao_recusados_sem_gastar_o_codigo(cofre):
    c = codigo_do(cofre)
    recusa(cofre, c, "CONFIRMACAO_DIFERENTE", params={**P, "hora": "10:00"})
    cofre.consumir(c, 7, "agendar", P, 2)


def test_ordem_das_chaves_nao_importa(cofre):
    c = codigo_do(cofre, params={"a": 1, "b": 2})
    cofre.consumir(c, 7, "agendar", {"b": 2, "a": 1}, 2)


def test_codigo_de_outro_cliente_ou_outra_acao_parece_inexistente(cofre):
    c = codigo_do(cofre)
    recusa(cofre, c, "CONFIRMACAO_INVALIDA", cliente=8)
    recusa(cofre, c, "CONFIRMACAO_INVALIDA", acao="cancelar_agendamento")
    cofre.consumir(c, 7, "agendar", P, 2)                     # o dono ainda consegue usar


def test_codigo_expira_depois_de_10_minutos(cofre):
    valido = codigo_do(cofre)
    cofre.relogio.avancar(minutes=9)
    cofre.consumir(valido, 7, "agendar", P, 2)                # com 9 minutos ainda vale
    vencido = codigo_do(cofre)
    cofre.relogio.avancar(minutes=11)
    recusa(cofre, vencido, "CONFIRMACAO_INVALIDA")


def test_codigo_inexistente_e_minusculas(cofre):
    recusa(cofre, "ZZZZZZ", "CONFIRMACAO_INVALIDA")
    c = codigo_do(cofre)
    cofre.consumir(c.lower(), 7, "agendar", P, 2)


def test_cofre_cheio_descarta_o_mais_antigo(cofre):
    primeiro = codigo_do(cofre)
    for _ in range(3):
        codigo_do(cofre)
    recusa(cofre, primeiro, "CONFIRMACAO_INVALIDA")


def test_emitir_limpa_os_expirados(cofre):
    antigo = codigo_do(cofre)
    cofre.relogio.avancar(minutes=30)
    codigo_do(cofre)
    assert antigo not in cofre._pendentes


def test_turnos_so_crescem(cofre):
    turnos = [cofre.proximo_turno() for _ in range(5)]
    assert turnos == sorted(set(turnos)) and turnos[0] >= 1


def test_propor_nao_grava_e_instrui_o_modelo(cofre):
    ctx = Contexto(conn=None, cliente_id=7, confirmacoes=cofre, turno=1)
    r = propor(ctx, 7, "agendar", P, {"pet": "Rex"})
    assert r["gravado"] is False and r["requer_confirmacao"] is True and r["resumo"] == {"pet": "Rex"}
    assert r["codigo_confirmacao"] in r["instrucao"] and "NOVA mensagem" in r["instrucao"]


def test_conferir_exige_texto_e_cofre(cofre):
    ctx = Contexto(conn=None, cliente_id=7, confirmacoes=cofre, turno=2)
    for ruim in (None, "", 123, ["A"]):
        with pytest.raises(ErroFerramenta) as e:
            conferir(ctx, 7, "agendar", P, ruim)
        assert e.value.codigo == "PARAMETRO_INVALIDO"
    sem_cofre = Contexto(conn=None, cliente_id=7)
    with pytest.raises(ErroFerramenta) as e:
        conferir(sem_cofre, 7, "agendar", P, "ABC123")
    assert e.value.codigo == "CONFIRMACAO_INDISPONIVEL"
    with pytest.raises(ErroFerramenta) as e:
        propor(sem_cofre, 7, "agendar", P, {})
    assert e.value.codigo == "CONFIRMACAO_INDISPONIVEL"