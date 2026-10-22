import re
from datetime import date, datetime, time, timedelta

from .base import ErroFerramenta, escapar_like, exigir_inteiro, exigir_texto, ferramenta

DIAS = ["segunda","terça","quarta","quinta","sexta","sábado","domingo"]
DURACAO_SLOT = timedelta(minutes=30)        # cada atendimento ocupa um horário de 30 min
ANTECEDENCIA = timedelta(minutes=60)        # hoje, só horários com pelo menos 1 hora de folga
MAX_DIAS_A_FRENTE = 60
# Mesmos status que o banco considera "ativos" no índice único de agendamento.
STATUS_ATIVOS = ("agendado","confirmado","concluido")


def _agora():
    """
    Horário atual. Fica numa função para os testes poderem fixar a hora.
    """
    return datetime.now()

def hhmm(valor):
    """
    TIME do MySQL (time) -> 'HH:MM'.
    """
    minutos = int(valor.total_seconds() // 60)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def exigir_data(valor, nome):
    if not isinstance(valor,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor.strip()):
        raise ErroFerramenta("PARAMETRO_INVALIDO",
                             f"'{nome}' deve ser um texto no formato AAAA-MM-DD, por exemplo 2026-10-20.")
    try:
        return datetime.strptime(valor.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'{nome}' não é uma data válida.")


@ferramenta(
    nome="listar_veterinarios",
    descricao=(
        "Lista os veterinarios com especialidade, loja onde atendem e dias e horários de atendimento. "
        "Pode filtrar por especialidade ou por loja."
    ),
    parametros={
        "especialidade": {"tipo": "string", "obrigatorio": False,
                          "descricao": "Opcional. Por exemplo: 'dermatologia' ou 'felinos'."},
        "loja_id": {"tipo": "integer", "obrigatorio": False,
                    "descricao": "Opcional. Mostra so os veterinarios dessa loja."},
    },
)
def listar_veterinarios(ctx, especialidade=None, loja_id=None):
    filtros, params = [],[]
    if especialidade is not None:
        especialidade = exigir_texto(especialidade, "especialidade", max_len=60)
        filtros.append("v.especialidade LIKE %s")       # %s é placeholder para parametros da consulta.
        params.append(f"%{escapar_like(especialidade)}%")
    if loja_id is not None:
        loja_id = exigir_inteiro(loja_id, "loja_id")
        filtros.append("v.loja_id = %s")
        params.append(loja_id)
    sql = ("SELECT v.id, v.nome, v.crmv, v.especialidade, v.loja_id, l.nome_fantasia AS loja "
           "FROM veterinario v LEFT JOIN loja l ON l.id = v.loja_id")
    if filtros:
        sql += " WHERE " + " AND ".join(filtros) # AND.join adiciona um AND entre os filtros que existem na lista.
    sql += " ORDER BY v.nome"

    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        vets = cur.fetchall()
        janelas = {}
        if vets:
            marcadores = ', '.join(["%s"] * len(vets))
            cur.execute(
                "SELECT veterinario_id, dia_semana, hora_inicio, hora_fim FROM horario_atendimento "
                f"WHERE veterinario_id IN ({marcadores}) ORDER BY veterinario_id, dia_semana, hora_inicio",
                [vet["id"] for vet in vets]
                )
            for hor in cur.fetchall():
                por_dia = janelas.setdefault(hor["veterinario_id"], {})   # obtém uma estrutura existente ou cria uma nova se a chave ainda não existir.
                por_dia.setdefault(hor["dia_semana"], []).append(f"{hhmm(hor['hora_inicio'])}-{hhmm(hor['hora_fim'])}")
    finally:
        cur.close()

    resultado = []
    for v in vets:
        atendimento = [{"dia": DIAS[dia - 1], "janelas": lista}
                       for dia, lista in sorted(janelas.get(v["id"], {}).items())]
        resultado.append({"veterinario_id": v["id"], "nome": v["nome"], "crmv": v["crmv"],
                          "especialidade": v["especialidade"], "loja_id": v["loja_id"], "loja": v["loja"],
                          "atendimento": atendimento
                          })
    return {"quantidade": len(resultado), "veterinarios": resultado}     


@ferramenta(
    nome="consultar_horarios_disponiveis",
    descricao=(
        "Mostra os horários LIVRES de atendimento (de 30 em 30 minutos) dos veterinários em uma data. "
        "A data deve estar no formato AAAA-MM-DD, não pode estar no passado e vai até 60 dias a frente. "
        "Hoje, só aparecem horários com pelo menos 1 hora de antecedência. "
        "Só lista veterinários que atendem naquele dia da semana."
    ),
    parametros={
        "data": {"tipo": "string", "obrigatorio": True,
                 "descricao": "Data desejada no formato AAAA-MM-DD, por exemplo 2026-10-20."},
        "veterinario_id": {"tipo": "integer", "obrigatorio": False,
                           "descricao": "Opcional. Restringe a um veterinario (obtido em listar_veterinarios)."},
        "especialidade": {"tipo": "string", "obrigatorio": False,
                          "descricao": "Opcional. Restringe a uma especialidade, por exemplo 'cardiologia'."},
    },
)
def consultar_horarios_disponiveis(ctx, data, veterinario_id=None, especialidade=None):
    dia = exigir_data(data, "data")
    agora = _agora()
    if dia < agora.date():
        raise ErroFerramenta("PARAMETRO_INVALIDO", "A data não pode estar no passado.")
    if dia > agora.date() + timedelta(days=MAX_DIAS_A_FRENTE):
        raise ErroFerramenta("PARAMETRO_INVALIDO",
                             f"Só é possivel consultar ate {MAX_DIAS_A_FRENTE} dias a frente.")
    if veterinario_id is not None:
        veterinario_id = exigir_inteiro(veterinario_id, "veterinario_id")
    if especialidade is not None:
        especialidade = exigir_texto(especialidade, "especialidade", max_len=60)

    filtros, params = [], []
    if veterinario_id is not None:
        filtros.append("v.id = %s")
        params.append(veterinario_id)
    if especialidade is not None:
        filtros.append("v.especialidade LIKE %s")
        params.append(f"%{escapar_like(especialidade)}%")
    sql = ("SELECT v.id, v.nome, v.especialidade, v.loja_id, l.nome_fantasia AS loja "
           "FROM veterinario v LEFT JOIN loja l ON l.id = v.loja_id")
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY v.nome"

    inicio_dia = datetime.combine(dia, time.min)
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        vets = cur.fetchall()
        if veterinario_id is not None and not vets:
            # Sem resultado pode ser id inexistente OU filtros que nao combinam: so o primeiro e erro.
            cur.execute("SELECT id FROM veterinario WHERE id = %s", (veterinario_id,))
            if cur.fetchone() is None:
                raise ErroFerramenta("VETERINARIO_NAO_ENCONTRADO", f"Nao existe veterinario com id {veterinario_id}.")
        janelas, ocupados = {}, set()
        if vets:
            ids = [v["id"] for v in vets]
            marcadores = ", ".join(["%s"] * len(ids))
            cur.execute(
                "SELECT veterinario_id, hora_inicio, hora_fim FROM horario_atendimento "
                f"WHERE dia_semana = %s AND veterinario_id IN ({marcadores}) ORDER BY hora_inicio",
                [dia.isoweekday()] + ids)
            for h in cur.fetchall():
                janelas.setdefault(h["veterinario_id"], []).append((h["hora_inicio"], h["hora_fim"]))
            status = ", ".join(["%s"] * len(STATUS_ATIVOS))
            cur.execute(
                "SELECT veterinario_id, data_hora FROM agendamento "
                f"WHERE veterinario_id IN ({marcadores}) AND data_hora >= %s AND data_hora < %s "
                f"AND status IN ({status})",
                ids + [inicio_dia, inicio_dia + timedelta(days=1)] + list(STATUS_ATIVOS))
            ocupados = {(r["veterinario_id"], r["data_hora"]) for r in cur.fetchall()}
    finally:
        cur.close()

    limite = agora + ANTECEDENCIA if dia == agora.date() else None
    resultado, total = [], 0
    for v in vets:
        if v["id"] not in janelas:                 # não atende neste dia da semana
            continue
        livres = []
        for ini, fim in janelas[v["id"]]:
            t, fim_janela = inicio_dia + ini, inicio_dia + fim
            while t + DURACAO_SLOT <= fim_janela:
                if (v["id"], t) not in ocupados and (limite is None or t >= limite):
                    livres.append(t.strftime("%H:%M"))
                t += DURACAO_SLOT
        total += len(livres)
        resultado.append({"veterinario_id": v["id"], "nome": v["nome"], "especialidade": v["especialidade"],
                          "loja_id": v["loja_id"], "loja": v["loja"],
                          "horarios_livres": livres, "quantidade": len(livres)})
    return {"data": dia.isoformat(), "dia_semana": DIAS[dia.weekday()],
            "duracao_minutos": int(DURACAO_SLOT.total_seconds() // 60),
            "total_horarios_livres": total, "veterinarios": resultado}