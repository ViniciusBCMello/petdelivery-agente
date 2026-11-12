"""agendar e cancelar_agendamento, com o banco de verdade (tudo é desfeito no fim de cada teste)."""
import dataclasses
from datetime import date, timedelta

import pytest

from app.tools import agendar as modulo_agendar
from app.tools import executar
from app.tools.agendar import ESPECIALIDADES_POR_TIPO


# ------------------------------------------------------------------ apoio
def donos(env, quantos=2):
    """Clientes que têm pet (e um pet de cada)."""
    linhas = env.sql("SELECT cliente_id, MIN(animal_id) FROM perfil_pet GROUP BY cliente_id ORDER BY cliente_id LIMIT %s", (quantos,))
    return [(c, a) for c, a in linhas]


def vets(env):
    """{'cardiologia': id, ...} (uma entrada por especialidade; a 1ª em caso de repetição)."""
    r = {}
    for vid, esp in env.sql("SELECT id, especialidade FROM veterinario ORDER BY id"):
        r.setdefault(esp.casefold(), vid)
    return r


def livre(env, vet_id, a_partir_de=10, indice=0):
    """'AAAA-MM-DD HH:MM' de um horário LIVRE do veterinário, daqui a alguns dias."""
    ctx = env.como(1)
    for d in range(a_partir_de, a_partir_de + 20):
        dia = date.today() + timedelta(days=d)
        quadro = executar("consultar_horarios_disponiveis", {"data": dia.isoformat(), "veterinario_id": vet_id}, ctx)["dados"]
        for v in quadro["veterinarios"]:
            if len(v["horarios_livres"]) > indice:
                return f"{dia.isoformat()} {v['horarios_livres'][indice]}"
    raise AssertionError("sem horário livre")


def pedido(animal, vet, hora, tipo="consulta", **extra):
    return {"animal_id": animal, "veterinario_id": vet, "data_hora": hora, "tipo": tipo, **extra}


def contar(env, cliente=None):
    if cliente is None:
        return env.sql("SELECT COUNT(*) FROM agendamento")[0][0]
    return env.sql("SELECT COUNT(*) FROM agendamento WHERE cliente_id = %s", (cliente,))[0][0]


def propor(env, ctx, args):
    r = executar("agendar", args, ctx)
    assert r["ok"], r
    return r["dados"]["codigo_confirmacao"]


def confirmar(env, ctx, args, codigo):
    """Confirma numa mensagem POSTERIOR (turno + 1)."""
    return executar("agendar", {**args, "confirmacao": codigo}, dataclasses.replace(ctx, turno=ctx.turno + 1))


def erro(r):
    assert r["ok"] is False, r
    return r["erro"]["codigo"]


@pytest.fixture()
def caso(escrita):
    """Um cliente com pet, um veterinário de clínica geral e um horário livre."""
    (cli, pet), (cli2, pet2) = donos(escrita)
    vet = vets(escrita)["clínica geral"]
    hora = livre(escrita, vet)
    return type("Caso", (), dict(env=escrita, cli=cli, pet=pet, cli2=cli2, pet2=pet2, vet=vet, hora=hora,
                                 ctx=escrita.como(cli), args=pedido(pet, vet, hora)))


# ================================================================ agendar: fluxo
def test_a_proposta_nao_grava_e_devolve_resumo_e_codigo(caso):
    antes = contar(caso.env)
    r = executar("agendar", caso.args, caso.ctx)
    assert r["ok"] and r["dados"]["gravado"] is False and r["dados"]["requer_confirmacao"]
    assert r["dados"]["codigo_confirmacao"] and contar(caso.env) == antes
    assert caso.env.conn.commits == 0                               # a proposta nem chega a fazer commit
    resumo = r["dados"]["resumo"]
    assert resumo["data_hora"] == caso.hora and resumo["tipo"] == "consulta"
    assert {"pet", "veterinario", "especialidade", "loja", "dia_semana"} <= set(resumo)


def test_confirmar_grava_com_status_agendado(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    r = confirmar(caso.env, caso.ctx, caso.args, cod)
    assert r["ok"] and r["dados"]["gravado"] is True and r["dados"]["status"] == "agendado"
    assert caso.env.conn.commits == 1                               # e a gravação foi efetivada (commit)
    linha = caso.env.sql("SELECT cliente_id, animal_id, veterinario_id, tipo, status, data_hora FROM agendamento WHERE id = %s",
                         (r["dados"]["agendamento_id"],))[0]
    assert linha[:5] == (caso.cli, caso.pet, caso.vet, "consulta", "agendado") and str(linha[5])[:16] == caso.hora


def test_o_horario_deixa_de_aparecer_como_livre_depois_de_agendar(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    confirmar(caso.env, caso.ctx, caso.args, cod)
    dia, hora = caso.hora.split(" ")
    quadro = executar("consultar_horarios_disponiveis", {"data": dia, "veterinario_id": caso.vet}, caso.ctx)["dados"]
    assert hora not in quadro["veterinarios"][0]["horarios_livres"]


def test_aparece_em_meus_agendamentos(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    novo = confirmar(caso.env, caso.ctx, caso.args, cod)["dados"]["agendamento_id"]
    lista = executar("listar_meus_agendamentos", {}, caso.ctx)["dados"]["agendamentos"]
    assert novo in [a["agendamento_id"] for a in lista]


def test_observacao_e_gravada_normalizada(caso):
    args = {**caso.args, "observacao": "  coceira   forte \n nas orelhas "}
    cod = propor(caso.env, caso.ctx, args)
    novo = confirmar(caso.env, caso.ctx, args, cod)["dados"]["agendamento_id"]
    assert caso.env.sql("SELECT observacao FROM agendamento WHERE id = %s", (novo,))[0][0] == "coceira forte nas orelhas"


def test_aceita_formatos_de_data_hora_equivalentes(caso):
    for formato in (caso.hora, caso.hora.replace(" ", "T"), caso.hora + ":00"):
        assert executar("agendar", {**caso.args, "data_hora": formato}, caso.ctx)["ok"], formato


# ======================================================= agendar: confirmação
def test_codigo_so_vale_uma_vez(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    assert confirmar(caso.env, caso.ctx, caso.args, cod)["ok"]
    antes = contar(caso.env)
    assert erro(confirmar(caso.env, caso.ctx, caso.args, cod)) in ("CONFIRMACAO_INVALIDA", "HORARIO_INDISPONIVEL")
    assert contar(caso.env) == antes


def test_confirmar_na_mesma_mensagem_e_recusado_e_nao_grava(caso):
    antes = contar(caso.env)
    cod = propor(caso.env, caso.ctx, caso.args)
    r = executar("agendar", {**caso.args, "confirmacao": cod}, caso.ctx)       # mesmo turno
    assert erro(r) == "CONFIRMACAO_PREMATURA" and contar(caso.env) == antes


def test_confirmar_com_dados_diferentes_do_resumo_e_recusado(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    outro = livre(caso.env, caso.vet, indice=3)
    ctx2 = dataclasses.replace(caso.ctx, turno=2)
    for alterado in ({"data_hora": outro}, {"tipo": "exame"}, {"observacao": "mudei"}):
        r = executar("agendar", {**caso.args, **alterado, "confirmacao": cod}, ctx2)
        assert erro(r) in ("CONFIRMACAO_DIFERENTE",), alterado
    assert confirmar(caso.env, caso.ctx, caso.args, cod)["ok"]                  # o original ainda funciona


def test_codigo_inventado_e_recusado(caso):
    assert erro(confirmar(caso.env, caso.ctx, caso.args, "ABC123")) == "CONFIRMACAO_INVALIDA"


def test_codigo_de_outro_cliente_e_recusado(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    outro_ctx = caso.env.como(caso.cli2)
    args2 = pedido(caso.pet2, caso.vet, caso.hora)
    assert erro(confirmar(caso.env, outro_ctx, args2, cod)) == "CONFIRMACAO_INVALIDA"


def test_codigo_de_cancelamento_nao_serve_para_agendar(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    confirmar(caso.env, caso.ctx, caso.args, cod)
    novo = caso.env.sql("SELECT MAX(id) FROM agendamento")[0][0]
    cod_cancel = executar("cancelar_agendamento", {"agendamento_id": novo}, caso.ctx)["dados"]["codigo_confirmacao"]
    outra_hora = livre(caso.env, caso.vet, indice=4)
    assert erro(confirmar(caso.env, caso.ctx, pedido(caso.pet, caso.vet, outra_hora), cod_cancel)) == "CONFIRMACAO_INVALIDA"


def test_codigo_expirado_e_recusado(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    caso.env.relogio.avancar(minutes=11)
    assert erro(confirmar(caso.env, caso.ctx, caso.args, cod)) == "CONFIRMACAO_INVALIDA"


def test_sem_cofre_a_ferramenta_recusa(caso):
    sem = dataclasses.replace(caso.ctx, confirmacoes=None)
    assert erro(executar("agendar", caso.args, sem)) == "CONFIRMACAO_INDISPONIVEL"


# ===================================================== agendar: regras de negócio
def test_exige_login(caso):
    assert erro(executar("agendar", caso.args, caso.env.como(None))) == "NAO_AUTENTICADO"


def test_nao_aceita_cliente_id_como_argumento(caso):
    assert erro(executar("agendar", {**caso.args, "cliente_id": caso.cli2}, caso.ctx)) == "PARAMETRO_INVALIDO"


def test_pet_de_outro_cliente_e_pet_inexistente_dao_o_mesmo_erro(caso):
    alheio = executar("agendar", pedido(caso.pet2, caso.vet, caso.hora), caso.ctx)
    inexistente = executar("agendar", pedido(999999, caso.vet, caso.hora), caso.ctx)
    assert erro(alheio) == "PET_NAO_ENCONTRADO" and alheio == inexistente


def test_veterinario_inexistente(caso):
    assert erro(executar("agendar", pedido(caso.pet, 999999, caso.hora), caso.ctx)) == "VETERINARIO_NAO_ENCONTRADO"


ESPECIALIDADES = ["clínica geral", "dermatologia", "cardiologia", "ortopedia", "cirurgia", "felinos", "oftalmologia"]


@pytest.mark.parametrize("tipo", ["consulta", "exame", "cirurgia"])
@pytest.mark.parametrize("esp", ESPECIALIDADES)
def test_regra_de_especialidade_por_tipo(escrita, esp, tipo):
    (cli, pet), _ = donos(escrita)
    vet = vets(escrita)[esp]
    ctx = escrita.como(cli)
    r = executar("agendar", pedido(pet, vet, livre(escrita, vet), tipo), ctx)
    aceitas = ESPECIALIDADES_POR_TIPO[tipo]
    deve_aceitar = aceitas is None or esp in {e.casefold() for e in aceitas}
    if deve_aceitar:
        assert r["ok"], r
    else:
        assert erro(r) == "TIPO_NAO_ATENDIDO" and "feito por" in r["erro"]["mensagem"]


def test_mapeamento_de_especialidades_e_o_combinado():
    assert ESPECIALIDADES_POR_TIPO == {
        "consulta": None,
        "exame": ("Clínica geral", "Cardiologia", "Oftalmologia", "Dermatologia"),
        "cirurgia": ("Cirurgia", "Ortopedia"),
    }


def test_tipo_invalido(caso):
    for ruim in ("vacina", "", 5, None):
        assert erro(executar("agendar", {**caso.args, "tipo": ruim}, caso.ctx)) == "PARAMETRO_INVALIDO", ruim


@pytest.mark.parametrize("ruim", ["05/11/2026 09:30", "2026-11-05", "2026-11-05 25:00", "2026-02-30 09:30", "amanha 9h", "", 20261105, None])
def test_data_hora_invalida(caso, ruim):
    assert erro(executar("agendar", {**caso.args, "data_hora": ruim}, caso.ctx)) == "PARAMETRO_INVALIDO"


def test_horario_no_passado_e_alem_de_60_dias(caso):
    ontem = (date.today() - timedelta(days=1)).isoformat() + " 09:00"
    longe = (date.today() + timedelta(days=90)).isoformat() + " 09:00"
    for h in (ontem, longe):
        assert erro(executar("agendar", {**caso.args, "data_hora": h}, caso.ctx)) == "PARAMETRO_INVALIDO", h


def test_horario_fora_da_grade_ou_do_expediente(caso):
    dia = caso.hora.split(" ")[0]
    for h in (f"{dia} 09:15", f"{dia} 03:00", f"{dia} 23:30"):
        assert erro(executar("agendar", {**caso.args, "data_hora": h}, caso.ctx)) == "HORARIO_INDISPONIVEL", h


def test_dia_em_que_o_veterinario_nao_atende(caso):
    domingo = date.today() + timedelta(days=10)
    domingo += timedelta(days=(7 - domingo.isoweekday()) % 7)           # próximo domingo
    r = executar("agendar", {**caso.args, "data_hora": f"{domingo} 10:00"}, caso.ctx)
    assert erro(r) == "HORARIO_INDISPONIVEL"


def test_horario_ocupado_por_outro_cliente(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    confirmar(caso.env, caso.ctx, caso.args, cod)
    r = executar("agendar", pedido(caso.pet2, caso.vet, caso.hora), caso.env.como(caso.cli2))
    assert erro(r) == "HORARIO_INDISPONIVEL"


def test_corrida_dois_clientes_com_o_mesmo_horario(caso):
    ctx2 = caso.env.como(caso.cli2)
    args2 = pedido(caso.pet2, caso.vet, caso.hora)
    cod1, cod2 = propor(caso.env, caso.ctx, caso.args), propor(caso.env, ctx2, args2)     # os dois viram "livre"
    assert confirmar(caso.env, caso.ctx, caso.args, cod1)["ok"]
    assert erro(confirmar(caso.env, ctx2, args2, cod2)) == "HORARIO_INDISPONIVEL"
    assert caso.env.sql("SELECT COUNT(*) FROM agendamento WHERE veterinario_id = %s AND data_hora = %s "
                        "AND status IN ('agendado','confirmado','concluido')", (caso.vet, caso.hora))[0][0] == 1


def test_o_banco_barra_a_dupla_reserva_mesmo_se_a_checagem_falhar(caso, monkeypatch):
    """Última linha de defesa: se a regra da aplicação deixasse passar, a chave única do MySQL segura."""
    cod = propor(caso.env, caso.ctx, caso.args)
    confirmar(caso.env, caso.ctx, caso.args, cod)
    ctx2 = caso.env.como(caso.cli2)
    args2 = pedido(caso.pet2, caso.vet, caso.hora)
    monkeypatch.setattr(modulo_agendar, "_validar_agendamento",
                        lambda ctx, *a, **k: {"tipo": "consulta", "pet": "x", "veterinario": "x", "especialidade": "x",
                                              "loja": "x", "data_hora": caso.hora, "dia_semana": "x"})
    # Com a validação da aplicação "quebrada" (diz que está tudo livre) e um código válido, só o banco impede:
    cod_forjado = caso.env.cofre.emitir(caso.cli2, "agendar", {**args2, "observacao": None}, 1)
    r = executar("agendar", {**args2, "confirmacao": cod_forjado}, dataclasses.replace(ctx2, turno=2))
    assert erro(r) == "HORARIO_INDISPONIVEL"
    assert caso.env.sql("SELECT COUNT(*) FROM agendamento WHERE veterinario_id = %s AND data_hora = %s "
                        "AND status IN ('agendado','confirmado','concluido')", (caso.vet, caso.hora))[0][0] == 1
    assert executar("listar_meus_pets", {}, ctx2)["ok"]                 # a conexão continua utilizável


def test_mesmo_pet_nao_pode_ter_dois_agendamentos_no_mesmo_horario(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    confirmar(caso.env, caso.ctx, caso.args, cod)
    # outro veterinário que ESTÁ livre exatamente nesse horário: só a regra do pet pode barrar
    dia, hora = caso.hora.split(" ")
    quadro = executar("consultar_horarios_disponiveis", {"data": dia}, caso.ctx)["dados"]["veterinarios"]
    outro = next((v["veterinario_id"] for v in quadro if v["veterinario_id"] != caso.vet and hora in v["horarios_livres"]), None)
    assert outro, "os dados de demonstração deveriam ter outro veterinário livre nesse horário"
    r = executar("agendar", pedido(caso.pet, outro, caso.hora), caso.ctx)
    assert erro(r) == "PET_JA_TEM_AGENDAMENTO"


def test_observacao_grande_demais(caso):
    assert erro(executar("agendar", {**caso.args, "observacao": "x" * 201}, caso.ctx)) == "PARAMETRO_INVALIDO"


# ======================================================= cancelar_agendamento
@pytest.fixture()
def marcado(caso):
    cod = propor(caso.env, caso.ctx, caso.args)
    caso.ag = confirmar(caso.env, caso.ctx, caso.args, cod)["dados"]["agendamento_id"]
    return caso


def status_de(env, ag_id):
    return env.sql("SELECT status FROM agendamento WHERE id = %s", (ag_id,))[0][0]


def cancelar(env, ctx, ag_id, codigo=None, turno_extra=0):
    args = {"agendamento_id": ag_id, **({"confirmacao": codigo} if codigo else {})}
    return executar("cancelar_agendamento", args, dataclasses.replace(ctx, turno=ctx.turno + turno_extra))


def test_cancelar_proposta_nao_altera(marcado):
    r = cancelar(marcado.env, marcado.ctx, marcado.ag)
    assert r["ok"] and r["dados"]["gravado"] is False and r["dados"]["resumo"]["agendamento_id"] == marcado.ag
    assert status_de(marcado.env, marcado.ag) == "agendado"


def test_cancelar_confirmado_muda_o_status_e_libera_o_horario(marcado):
    cod = cancelar(marcado.env, marcado.ctx, marcado.ag)["dados"]["codigo_confirmacao"]
    commits = marcado.env.conn.commits
    r = cancelar(marcado.env, marcado.ctx, marcado.ag, cod, turno_extra=1)
    assert r["ok"] and r["dados"]["status"] == "cancelado" and status_de(marcado.env, marcado.ag) == "cancelado"
    assert marcado.env.conn.commits == commits + 1                  # cancelamento efetivado (commit)
    dia, hora = marcado.hora.split(" ")
    quadro = executar("consultar_horarios_disponiveis", {"data": dia, "veterinario_id": marcado.vet}, marcado.ctx)["dados"]
    assert hora in quadro["veterinarios"][0]["horarios_livres"]
    cod2 = propor(marcado.env, marcado.ctx, marcado.args)                       # e dá para agendar de novo
    assert confirmar(marcado.env, marcado.ctx, marcado.args, cod2)["ok"]


def test_cancelar_no_mesmo_turno_e_recusado(marcado):
    cod = cancelar(marcado.env, marcado.ctx, marcado.ag)["dados"]["codigo_confirmacao"]
    assert erro(cancelar(marcado.env, marcado.ctx, marcado.ag, cod)) == "CONFIRMACAO_PREMATURA"
    assert status_de(marcado.env, marcado.ag) == "agendado"


def test_cancelar_codigo_de_outro_agendamento_ou_de_outro_cliente(marcado):
    cod = cancelar(marcado.env, marcado.ctx, marcado.ag)["dados"]["codigo_confirmacao"]
    outro_ctx = marcado.env.como(marcado.cli2)
    assert erro(cancelar(marcado.env, outro_ctx, marcado.ag, cod, turno_extra=1)) == "AGENDAMENTO_NAO_ENCONTRADO"
    assert erro(cancelar(marcado.env, marcado.ctx, marcado.ag + 1000, cod, turno_extra=1)) == "AGENDAMENTO_NAO_ENCONTRADO"
    assert status_de(marcado.env, marcado.ag) == "agendado"


def test_cancelar_agendamento_de_outro_cliente_e_igual_a_inexistente(marcado):
    outro_ctx = marcado.env.como(marcado.cli2)
    alheio = cancelar(marcado.env, outro_ctx, marcado.ag)
    inexistente = cancelar(marcado.env, outro_ctx, 999999)
    assert erro(alheio) == "AGENDAMENTO_NAO_ENCONTRADO" and alheio == inexistente


def test_cancelar_exige_login_e_nao_aceita_cliente_id(marcado):
    assert erro(cancelar(marcado.env, marcado.env.como(None), marcado.ag)) == "NAO_AUTENTICADO"
    r = executar("cancelar_agendamento", {"agendamento_id": marcado.ag, "cliente_id": 1}, marcado.ctx)
    assert erro(r) == "PARAMETRO_INVALIDO"


def test_nao_cancela_o_que_ja_esta_cancelado(marcado):
    cod = cancelar(marcado.env, marcado.ctx, marcado.ag)["dados"]["codigo_confirmacao"]
    cancelar(marcado.env, marcado.ctx, marcado.ag, cod, turno_extra=1)
    assert erro(cancelar(marcado.env, marcado.ctx, marcado.ag)) == "AGENDAMENTO_NAO_CANCELAVEL"


def test_nao_cancela_agendamento_concluido_ou_nao_compareceu(escrita):
    cli, ag = escrita.sql("SELECT cliente_id, id FROM agendamento WHERE status = 'concluido' AND data_hora < NOW() LIMIT 1")[0]
    assert erro(cancelar(escrita, escrita.como(cli), ag)) == "AGENDAMENTO_NAO_CANCELAVEL"
    cli, ag = escrita.sql("SELECT cliente_id, id FROM agendamento WHERE status = 'nao_compareceu' LIMIT 1")[0]
    assert erro(cancelar(escrita, escrita.como(cli), ag)) == "AGENDAMENTO_NAO_CANCELAVEL"


def test_nao_cancela_agendamento_que_ja_passou_mesmo_com_status_agendado(escrita):
    (cli, pet), _ = donos(escrita)
    vet = vets(escrita)["clínica geral"]
    antes = escrita.sql("SELECT COUNT(*) FROM agendamento")[0][0]
    escrita.sql("INSERT INTO agendamento (cliente_id, animal_id, veterinario_id, tipo, data_hora, status) "
                "VALUES (%s, %s, %s, 'consulta', NOW() - INTERVAL 3 DAY, 'agendado')", (cli, pet, vet))
    ag = escrita.sql("SELECT MAX(id) FROM agendamento")[0][0]
    r = cancelar(escrita, escrita.como(cli), ag)
    assert erro(r) == "AGENDAMENTO_NAO_CANCELAVEL" and "passou" in r["erro"]["mensagem"]


def test_cancelado_no_meio_tempo_nao_cancela_de_novo(marcado):
    cod = cancelar(marcado.env, marcado.ctx, marcado.ag)["dados"]["codigo_confirmacao"]
    marcado.env.sql("UPDATE agendamento SET status = 'cancelado' WHERE id = %s", (marcado.ag,))   # outro canal cancelou
    assert erro(cancelar(marcado.env, marcado.ctx, marcado.ag, cod, turno_extra=1)) == "AGENDAMENTO_NAO_CANCELAVEL"


def test_agendamento_confirmado_pela_recepcao_tambem_pode_ser_cancelado(marcado):
    marcado.env.sql("UPDATE agendamento SET status = 'confirmado' WHERE id = %s", (marcado.ag,))
    cod = cancelar(marcado.env, marcado.ctx, marcado.ag)["dados"]["codigo_confirmacao"]
    assert cancelar(marcado.env, marcado.ctx, marcado.ag, cod, turno_extra=1)["ok"]