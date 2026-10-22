"""
Base das ferramentas do agente: contexto, erro, registro e execução

Uma ferramenta é uma função Python comum, registrada em @ferramenta.
O modelo de linguagem **NUNCA** toca no banco: ele só **PEDE** uma ferramenta pelo
nome, com argumentos. Quem valida, executa e trata falhas é este módulo.
"""

import logging
from dataclasses import dataclass # Simplifica a criação de estruturas destinadas a armazenamento de dados.
from decimal import Decimal # Precisão decimal no float.
from typing import Any, Callable # Auxilia na documentação e na organização do código, indicando os tipos esperados para atributos e funções.

import mysql.connector

log = logging.getLogger("agente.ferramentas")


class ErroFerramenta(Exception):
    """
    Falha **esperada** de uma ferramenta (parâmtro inválido, item inexistente...)
    """

    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem

@dataclass
class Contexto:
    """
    O que a aplicação entrega a cada ferramenta. O modelo não controla nada disto.
    """

    conn: Any                       # Conexão aberta com o banco.
    cliente_id: int | None = None   # Vem da sessão (login), nunca de argumento do modelo.


@dataclass(frozen=True)
class Ferramenta:
    nome: str
    descricao: str
    parametros: dict               # {"nome": {"tipo": "integer"|"string", "descricao": "...", "obrigatorio": bool}}
    funcao: Callable


REGISTRO: dict[str, Ferramenta] = {}


def ferramenta(nome: str, descricao: str, parametros: dict):
    """
    Decorador que registra uma função como ferramenta do agente.
    """

    def registrar(funcao):
        if nome in REGISTRO:
            raise ValueError(f"Ferramenta duplicada: {nome}.")
        REGISTRO[nome] = Ferramenta(nome, descricao, parametros, funcao)
        return funcao

    return registrar


def especificacoes() -> list[dict]:
    """
    Descrição das ferramentas no formato que o LLM recebe (JSON Schema).

    O módulo do provedor de IA adapta estas especifiçoes ao seu formato.

    f: cada ferramenta registrada, coloque essa ferramenta temporariamente na variável
    k: key(chave) do dicionário
    v: value(valor) do dicionário
    """
    saida = []
    for f in REGISTRO.values():
        propriedades = {k: {"type": v["tipo"], "description": v["descricao"]} for k, v in f.parametros.items()}
        obrigatorios = [k for k,v in f.parametros.items() if v.get("obrigatorio")]
        saida.append({
            "name": f.nome,
            "description": f.descricao,
            "parameters": {"type": "object", "properties": propriedades, "required": obrigatorios, "additionalProperties": False},
        })
    return saida


# ---------------------------------------------------------------------------
# Validadores: tudo que chega do modelo é tratado como NÃO CONFIÁVEL
# ---------------------------------------------------------------------------
def exigir_inteiro(valor, nome:str, minino: int = 1) -> int:
    #validação bool; True não pode virar 1.
    if isinstance(valor, str) and valor.strip().isdigit():
        valor = int(valor)          # modelos as vezes mandam "5" em vez de 5
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'{nome} deve ser um número inteiro.")
    if valor < minino:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'{nome} deve ser maior ou igual a {minino}.")
    return valor


def exigir_texto(valor, nome: str, max_len: int = 1000) -> str:
    if not isinstance(valor, str):
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'{nome}' deve ser um texto.")
    valor = " ".join(valor.split())             # tira espacos e quebras de linha sobrando
    if not valor:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'{nome}' não pode ser vazio.")
    if len(valor) > max_len:
        raise ErroFerramenta("PARAMETRO_INVALIDO", f"'{nome}' deve ter no máximo {max_len} caracteres.")
    return valor


def escapar_like(texto: str) -> str:
    """Faz %, _ e \\ valerem como letras comuns dentro de um LIKE."""
    return texto.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")


def dinheiro(valor: Decimal) -> str:
    """
    Valor monetário como texto com 2 casas ('19.81'): evita erros de float.
    """
    return f"{valor:.2f}"


def exigir_cliente(ctx: Contexto) -> int:
    """Devolve o cliente LOGADO, ou recusa. É a unica fonte de identidade das ferramentas pessoais.

    O cliente vem da sessão (ctx.cliente_id), que o modelo nao controla: nenhuma ferramenta
    pessoal aceita cliente_id como argumento.
    """
    cliente_id = ctx.cliente_id
    if isinstance(cliente_id, bool) or not isinstance(cliente_id, int) or cliente_id < 1:
        raise ErroFerramenta("NAO_AUTENTICADO",
                             "Esta consulta exige que o cliente esteja identificado (login).")
    return cliente_id


# ---------------------------------------------------------------------------
# Execucao: uma porta de entrada, que nunca levanta exceção
# ---------------------------------------------------------------------------
def _erro(codigo: str, mensagem: str) -> dict:
    return {"ok": False, "erro": {"codigo": codigo, "mensagem": mensagem}}


def executar(nome: str, argumentos, ctx: Contexto) -> dict:
    """
    Valida e executa uma ferramenta.
    
    Devolve sempre {"ok": True, "dados": ...} ou {"ok": False, "erro": {...}}.
    Assim o orquestrador, e o agente, lidam com falhas como dados, não como exceções.
    """
    ferr = REGISTRO.get(nome)
    if ferr is None:
        return _erro("FERRAMENTA_DESCONHECIDA", f"A ferramenta '{nome}' não existe.")
    if argumentos is None:
        argumentos = {}
    if not isinstance(argumentos, dict):
        return _erro("PARAMETRO_INVALIDO", "Os argumentos devem ser um objeto com nome e valor.")

    # O modelo pode inventar parâmetros: só entram os que a ferramenta declarou.
    extras = sorted(set(argumentos) - set(ferr.parametros))
    if extras:
        return _erro("PARAMETRO_INVALIDO", f"Parâmetros não aceitos: {', '.join(extras)}.")
    faltando = [k for k, v in ferr.parametros.items() if v.get("obrigatorio") and argumentos.get(k) is None]
    if faltando:
        return _erro("PARAMETRO_INVALIDO", f"Faltam parametros obrigatorios: {', '.join(faltando)}.")

    try:
        dados = ferr.funcao(ctx, **argumentos)
        log.info("ferramenta=%s ok=True", nome)
        return {"ok": True, "dados": dados}
    except ErroFerramenta as e:
        log.info("ferramenta=%s ok=False codigo=%s", nome, e.codigo)
        return _erro(e.codigo, e.mensagem)
    except mysql.connector.Error:
        # O detalhe tecnico vai para o log; quem chamou recebe uma mensagem segura.
        log.exception("ferramenta=%s falha no banco de dados", nome)
        return _erro("SERVICO_INDISPONIVEL",
                     "Não foi possível consultar o banco de dados agora. Tente novamente em instantes.")
    except Exception:
        log.exception("ferramenta=%s erro inesperado", nome)
        return _erro("ERRO_INTERNO", "Ocorreu um erro inesperado ao executar a ferramenta.")