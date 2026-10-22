"""Ferramentas do CLIENTE (dados pessoais): perfil, pets, enderecos e agendamentos.

REGRA DE OURO: nenhuma destas ferramentas recebe cliente_id como parametro.
O cliente vem de ctx.cliente_id (sessao de login), que o modelo não controla.
"""
from .agenda import _agora
from .base import ErroFerramenta, exigir_cliente, exigir_texto, ferramenta

MAX_AGENDAMENTOS = 20
PERIODOS = ("futuros", "passados", "todos")


def _data_hora(valor):
    return None if valor is None else valor.strftime("%Y-%m-%d %H:%M")


@ferramenta(
    nome="consultar_meu_perfil",
    descricao="Mostra os dados cadastrais do cliente logado: nome, e-mail, telefone e desde quando e cliente. "
              "Nao mostra CPF.",
    parametros={},
)
def consultar_meu_perfil(ctx):
    cliente_id = exigir_cliente(ctx)
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT nome, email, telefone, criado_em FROM cliente WHERE id = %s", (cliente_id,))
        c = cur.fetchone()
    finally:
        cur.close()
    if c is None:
        raise ErroFerramenta("CLIENTE_NAO_ENCONTRADO", "Nao encontrei o cadastro do cliente desta sessao.")
    return {"nome": c["nome"], "email": c["email"], "telefone": c["telefone"],
            "cliente_desde": c["criado_em"].strftime("%Y-%m-%d")}


@ferramenta(
    nome="listar_meus_pets",
    descricao="Lista os pets do cliente logado, com especie, raca, idade em anos e peso em kg.",
    parametros={},
)
def listar_meus_pets(ctx):
    cliente_id = exigir_cliente(ctx)
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT a.id, a.nome, a.especie, a.raca, a.idade, a.peso FROM perfil_pet pp "
            "JOIN animal a ON a.id = pp.animal_id WHERE pp.cliente_id = %s ORDER BY a.nome", (cliente_id,))
        pets = cur.fetchall()
    finally:
        cur.close()
    return {"quantidade": len(pets),
            "pets": [{"animal_id": p["id"], "nome": p["nome"], "especie": p["especie"], "raca": p["raca"],
                      "idade_anos": p["idade"], "peso_kg": None if p["peso"] is None else float(p["peso"])}
                     for p in pets]}


@ferramenta(
    nome="listar_meus_enderecos",
    descricao="Lista os enderecos cadastrados do cliente logado (usados nas entregas).",
    parametros={},
)
def listar_meus_enderecos(ctx):
    cliente_id = exigir_cliente(ctx)
    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, rua, numero, complemento, bairro, cep, cidade, estado "
                    "FROM endereco WHERE cliente_id = %s ORDER BY id", (cliente_id,))
        enderecos = cur.fetchall()
    finally:
        cur.close()
    itens = []
    for e in enderecos:
        texto = f"{e['rua']}, {e['numero']}" + (f" - {e['complemento']}" if e["complemento"] else "")
        itens.append({"endereco_id": e["id"], "endereco": texto, "bairro": e["bairro"], "cep": e["cep"],
                      "cidade": e["cidade"], "estado": e["estado"]})
    return {"quantidade": len(itens), "enderecos": itens}


@ferramenta(
    nome="listar_meus_agendamentos",
    descricao=(
        "Lista os agendamentos (consulta, exame ou cirurgia) do cliente logado. "
        "periodo='futuros' (padrao): proximos agendamentos ainda ativos (agendado ou confirmado); "
        "'passados': ja ocorridos, em qualquer situacao; 'todos': tudo. Mostra ate 20."
    ),
    parametros={
        "periodo": {"tipo": "string", "obrigatorio": False,
                    "descricao": "Opcional: 'futuros' (padrao), 'passados' ou 'todos'."},
    },
)
def listar_meus_agendamentos(ctx, periodo="futuros"):
    cliente_id = exigir_cliente(ctx)
    periodo = exigir_texto(periodo, "periodo", max_len=20).lower()
    if periodo not in PERIODOS:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'periodo' deve ser um destes: {', '.join(PERIODOS)}.")

    agora = _agora()
    filtro, params, ordem = "", [cliente_id], "DESC"
    if periodo == "futuros":
        filtro, ordem = " AND ag.data_hora >= %s AND ag.status IN ('agendado', 'confirmado')", "ASC"
        params.append(agora)
    elif periodo == "passados":
        filtro = " AND ag.data_hora < %s"
        params.append(agora)

    cur = ctx.conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT ag.id, ag.tipo, ag.data_hora, ag.status, ag.observacao, a.nome AS pet, "
            "v.nome AS veterinario, v.especialidade, l.nome_fantasia AS loja "
            "FROM agendamento ag JOIN animal a ON a.id = ag.animal_id "
            "JOIN veterinario v ON v.id = ag.veterinario_id LEFT JOIN loja l ON l.id = v.loja_id "
            f"WHERE ag.cliente_id = %s{filtro} ORDER BY ag.data_hora {ordem}, ag.id {ordem} LIMIT %s",
            params + [MAX_AGENDAMENTOS + 1])
        linhas = cur.fetchall()
    finally:
        cur.close()
    ha_mais = len(linhas) > MAX_AGENDAMENTOS
    linhas = linhas[:MAX_AGENDAMENTOS]
    return {
        "periodo": periodo, "quantidade": len(linhas), "ha_mais_resultados": ha_mais,
        "agendamentos": [{"agendamento_id": l["id"], "tipo": l["tipo"], "data_hora": _data_hora(l["data_hora"]),
                          "status": l["status"], "pet": l["pet"], "veterinario": l["veterinario"],
                          "especialidade": l["especialidade"], "loja": l["loja"], "observacao": l["observacao"]}
                         for l in linhas],
    }