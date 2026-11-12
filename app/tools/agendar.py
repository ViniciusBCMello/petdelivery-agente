"""
Ferramentas que GRAVAM agendamentos: agendar e cancelar_agendamento.

Regras:
    - o cliente vem da sessão( nunca é argumento) e o pet precisa ser dele;
    - quem pode fazer o que vem da ESPECIALIADADE do veterinário (ESPECIALIDADES_POR_TIPO);
    - o horário precisa estar livre pelas MESMAS regras de consulta de horários;
    - nada é gravado sem a confirmação em duas etapas(confirmacao.py);
    - o banco é a última linha de defesa: dois agendamentos ativos no mesmo horário do mesmo
    veterinário são impossíveis( chave única).
"""
import re
from datetime import datetime

import mysql.connector
from mysql.connector import errorcode

from . import agenda
from .base import ErroFerramenta, exigir_texto, exigir_cliente, exigir_inteiro, ferramenta
from app.tools.confirmacao import conferir, propor

TIPOS = ("consulta", "exame", "cirurgia")
ESPECIALIDADES_POR_TIPO = {
    "consulta": None,
    "exame": ("Clínica geral", "Cardiologia", "Oftalmologia", "Dermatologia"),
    "cirurgia": ("Cirurgia","Ortopedia"),
}
STATUS_CANCELAVEIS = ("agendado", "confirmado")
MAX_OBSERVACAO = 200


def exigir_data_hora(valor, nome="data_hora") -> datetime:
    """Aceita 'AAAA-MM-DD HH:MM'"""
    modelo = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::00)?", valor.strip()) if isinstance(valor, str) else None
    if not modelo:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"''{nome} deve ser um texto no formato AAAA-MM-DD HH:MM, por exemplo 2026-11-05 09:30.")
    try:
        return datetime.strptime(f"{modelo[1]} {modelo[2]}:{modelo[3]}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'{nome}' não é uma data e hora válidas.")


def _tipo(valor) -> str:
    tipo = exigir_texto(valor, "tipo", max_len=20).lower()
    if tipo not in TIPOS:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'tipo' deve ser um destes {','.join(TIPOS)}.")
    return tipo 


def _um(ctx, sql, params):
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def _legivel(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# agendar
# ---------------------------------------------------------------------------
def _validar_agendamento(ctx, cliente_id, animal_id, veterinario_id, momento, tipo): 
    """Todas as regras de negócio. Roda nas DUAS etapas"""
    pet = _um(ctx, "SELECT a.id, a.nome FROM perfil_pet pp JOIN animal a ON a.id = pp.animal_id "
                    "WHERE pp.cliente_id = %s AND pp.animal_id = %s", (cliente_id, animal_id))
    if pet is None:
        raise ErroFerramenta("PET_NAO_ENCONTRADO",
                             "Não encontrei esse pet entre os pets do cliente. Use listar_meus_pets.")

    vet = _um(ctx, "SELECT V.id, v.nome, v.especialidade, l.nome_fantasia AS loja FROM veterinario v "
                    "LEFT JOIN loja l on l.id = v.loja_id WHERE v.id = %s", (veterinario_id,))
    if vet is None:
        raise ErroFerramenta("VETERINARIO_NAO_ENCONTRADO",
                             f"Não existe veterinário com id {veterinario_id}.")

    aceitas = ESPECIALIDADES_POR_TIPO[tipo]
    if aceitas is not None and vet["especialidade"].casefold() not in {e.casefold() for e in aceitas}:
                raise ErroFerramenta("TIPO_NAO_ATENDIDO",
                                     f"{vet['nome']} ({vet['especialidade']}) não faz {tipo}."
                                     f"{tipo.capitalize()} é feito por {', '.join(aceitas)}.")


    # Mesma regra de consultar_horarios_disponiveis data no passado, até 60 dias, grade de 30 min,
    # expediente, 1 hora de antecedência hoje, horário ocupado): uma só fonte da verdade.
    quadro = agenda.consultar_horarios_disponiveis(ctx, data=momento.date().isoformat(), veterinario_id=veterinario_id)
    entrada = next((v for v in quadro["veterinarios"] if v["veterinario_id"] == veterinario_id), None)
    if entrada is None:
        raise ErroFerramenta("HORARIO_INDISPONIVEL", f"{vet['nome']} não atende nesse horário.")
    if momento.strftime("%H:%M") not in entrada["horarios_livres"]:
        raise ErroFerramenta("HORARIO_INDISPONIVEL",
                             "Esse horário não está livre (ocupadp, fora do expediente...). Use a ferramenta consultar_horarios_disponiveis.")

    conflito = _um(ctx, "SELECT id FROM agendamento WHERE animal_id = %s and data_hora = %s "
                        "AND status IN ('agendado', 'confirmado', 'concluido')", (animal_id, momento))

    if conflito is not None:
        raise ErroFerramenta("PET_JA_TEM_AGENDAMENTO", f"{pet['nome']} já tem um agendamento para este horário.")

    return{"tipo": tipo, "pet": pet['nome'], "veterinario": vet['nome'], "especialidade": vet['especialidade'],
           "loja": vet['loja'], "data_hora": _legivel(momento), "dia_semana": agenda.DIAS[momento.weekday()]}


@ferramenta(
    nome="agendar",
    descricao=(
        "Agenda consulta, exame ou cirurgia para um pet do cliente logado, em DUAS ETAPAS. "
        "Etapa 1: chame SEM 'confirmacao'. Nada é gravado: volta um resumo e um código. Mostre o resumo ao cliente e "
        "pergunte se confirma. Etapa 2: só depois que o cliente responder em uma nova mensagem, chame de novo com os "
        "MESMOS parâmetros e confirmacao=<código>. Antes, descubra o pet (listar_meus_pets), o veterinário "
        "(listar_veterinarios) e um horário livre (consultar_horarios_disponiveis). Exame é feito por Clínica geral, "
        "Cardiologia, Oftalmologia ou Dermatologia; cirurgia por Cirurgia ou Ortopedia; consulta por qualquer um."
    ),
    parametros={
        "animal_id": {"tipo": "integer", "obrigatorio": True,
                      "descricao": "Id do pet (campo animal_id de listar_meus_pets)."},
        "veterinario_id": {"tipo": "integer", "obrigatorio": True,
                           "descricao": "Id do veterinário (listar_veterinarios)."},
        "data_hora": {"tipo": "string", "obrigatorio": True,
                      "descricao": "Data e hora no formato AAAA-MM-DD HH:MM, por exemplo 2026-11-05 09:30."},
        "tipo": {"tipo": "string", "obrigatorio": True, "descricao": "'consulta', 'exame' ou 'cirurgia'."},
        "observacao": {"tipo": "string", "obrigatorio": False,
                       "descricao": f"Opcional. Observação do cliente (até {MAX_OBSERVACAO} caracteres)."},
        "confirmacao": {"tipo": "string", "obrigatorio": False,
                        "descricao": "Só na etapa 2: o código recebido na etapa 1."},
    },
)
def agendar(ctx, animal_id, veterinario_id, data_hora, tipo, observacao=None, confirmacao=None):
    cliente_id = exigir_cliente(ctx)
    animal_id = exigir_inteiro(animal_id, "animal_id")
    veterinario_id = exigir_inteiro(veterinario_id, "veterinario_id")
    momento = exigir_data_hora(data_hora)
    tipo = _tipo(tipo)
    observacao = None if observacao is None else exigir_texto(observacao, "observacao", max_len=MAX_OBSERVACAO)

    resumo = _validar_agendamento(ctx, cliente_id, animal_id, veterinario_id, momento, tipo)
    resumo["observacao"] = observacao
    amarrado = {"animal_id": animal_id, "veterinario_id": veterinario_id, "data_hora": _legivel(momento),
                "tipo": tipo, "observacao": observacao}

    if confirmacao is None:
        return propor(ctx, cliente_id, "agendar", amarrado, resumo)

    conferir(ctx, cliente_id, "agendar", amarrado, confirmacao)
    cur = ctx.conn.cursor()
    try:
        cur.execute("INSERT INTO agendamento (cliente_id, animal_id, veterinario_id, tipo, data_hora, status, observacao) "
                    "VALUES (%s, %s, %s, %s, %s, 'agendado', %s)",
                    (cliente_id, animal_id, veterinario_id, tipo, momento, observacao))
        novo_id = cur.lastrowid
        ctx.conn.commit()
    except mysql.connector.IntegrityError as e:
        ctx.conn.rollback()
        if e.errno == errorcode.ER_DUP_ENTRY:       # alguém ocupou o horário no meio tempo: o banco barrou
            raise ErroFerramenta("HORARIO_INDISPONIVEL", "Esse horário acabou de ser ocupado. Escolha outro.")
        raise
    except Exception:
        ctx.conn.rollback()
        raise
    finally:
        cur.close()
    return {"gravado": True, "agendamento_id": novo_id, "status": "agendado", "resumo": resumo}


# ---------------------------------------------------------------------------
# cancelar_agendamento
# ---------------------------------------------------------------------------
@ferramenta(
    nome="cancelar_agendamento",
    descricao=(
        "Cancela um agendamento FUTURO do cliente logado (status agendado ou confirmado), em DUAS ETAPAS. "
        "Etapa 1: chame SEM 'confirmacao'. Nada é alterado: volta um resumo e um código. Mostre o resumo ao cliente e "
        "pergunte se confirma. Etapa 2: só depois que o cliente responder em uma nova mensagem, chame de novo com o "
        "MESMO agendamento_id e confirmacao=<código>. Cancelar libera o horário. "
        "O id vem de listar_meus_agendamentos."
    ),
    parametros={
        "agendamento_id": {"tipo": "integer", "obrigatorio": True,
                           "descricao": "Id do agendamento (campo agendamento_id de listar_meus_agendamentos)."},
        "confirmacao": {"tipo": "string", "obrigatorio": False,
                        "descricao": "Só na etapa 2: o código recebido na etapa 1."},
    },
)
def cancelar_agendamento(ctx, agendamento_id, confirmacao=None):
    cliente_id = exigir_cliente(ctx)
    agendamento_id = exigir_inteiro(agendamento_id, "agendamento_id")

    ag = _um(ctx, "SELECT ag.id, ag.tipo, ag.data_hora, ag.status, a.nome AS pet, v.nome AS veterinario, "
                  "v.especialidade, l.nome_fantasia AS loja FROM agendamento ag "
                  "JOIN animal a ON a.id = ag.animal_id JOIN veterinario v ON v.id = ag.veterinario_id "
                  "LEFT JOIN loja l ON l.id = v.loja_id WHERE ag.id = %s AND ag.cliente_id = %s",
             (agendamento_id, cliente_id))
    if ag is None:      # de outro cliente ou inexistente: mesmo erro
        raise ErroFerramenta("AGENDAMENTO_NAO_ENCONTRADO",
                             "Não encontrei esse agendamento entre os do cliente. Use listar_meus_agendamentos.")
    if ag["status"] not in STATUS_CANCELAVEIS:
        raise ErroFerramenta("AGENDAMENTO_NAO_CANCELAVEL", f"Este agendamento está '{ag['status']}' e não pode ser cancelado.")
    if ag["data_hora"] <= agenda._agora():
        raise ErroFerramenta("AGENDAMENTO_NAO_CANCELAVEL", "Este agendamento já passou e não pode ser cancelado.")

    resumo = {"agendamento_id": ag["id"], "tipo": ag["tipo"], "pet": ag["pet"], "veterinario": ag["veterinario"],
              "especialidade": ag["especialidade"], "loja": ag["loja"], "data_hora": _legivel(ag["data_hora"])}
    amarrado = {"agendamento_id": agendamento_id}

    if confirmacao is None:
        return propor(ctx, cliente_id, "cancelar_agendamento", amarrado, resumo)

    conferir(ctx, cliente_id, "cancelar_agendamento", amarrado, confirmacao)
    cur = ctx.conn.cursor()
    try:
        cur.execute("UPDATE agendamento SET status = 'cancelado' WHERE id = %s AND cliente_id = %s "
                    "AND status IN ('agendado', 'confirmado')", (agendamento_id, cliente_id))
        alteradas = cur.rowcount
        ctx.conn.commit()
    except Exception:
        ctx.conn.rollback()
        raise
    finally:
        cur.close()
    if alteradas != 1:      # mudou de situação entre a checagem e a gravação
        raise ErroFerramenta("AGENDAMENTO_NAO_CANCELAVEL", "Este agendamento mudou de situação e não pôde ser cancelado.")
    return {"gravado": True, "agendamento_id": agendamento_id, "status": "cancelado", "resumo": resumo}