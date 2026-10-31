"""
Provedor de LLM: o ÚNICO módulo que conhece a API de um fornecedor.

O resto do agente fala só com os tipos neutros daqui (Mensagem, ChamadaFerramenta...).
Para trocar de fornecedor (ou de modelo, nos testes finais) basta escrever outra
classe com o mesmo contrato (Provedor/Turno) e mudar criar_provedor().

Fornecedor atual: OpenAI, pela Responses API.
"""

import logging
from dataclasses import dataclass
import openai

log = logging.getLogger("agente.provedor")

MAX_SAIDA = 3000            # teto de tokens de saída por chamada


# ---------------------------------------------------------------------------
# Tipos neutros (não dependem de nenhum fornecedor)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Mensagem:
    papel: str              #"user" ou "assistant"
    texto: str

@dataclass(frozen=True)
class ChamadaFerramenta:
    """Pedido do modelo: 'execute esta ferramenta com estes argumentos'."""
    id: str
    nome: str
    argumentos_json: str        # texto JSON, exatamente como o modelo mandou


@dataclass(frozen=True)
class ResultadoFerramenta:
    """O que devolvemos ao modelo depois de executar uma chamada."""
    chamada_id: str
    conteudo: str               # texto JSON do envelope {"ok": ...}


@dataclass
class Uso:
    """Tokens gastos. O fornecedor informa; a soma do turno serve para custo e métricas."""
    entrada: int = 0
    saida: int = 0
    em_cache: int = 0            # parte da entrada que veio do cache (mais barata)
    raciocinio: int = 0          # parte da saída gasta "pensando"
    chamadas: int = 0            # quantas vezes o modelo foi chamado

    def somar(self, outro: "Uso") -> None:
        self.entrada += outro.entrada
        self.saida += outro.saida
        self.em_cache += outro.em_cache
        self.raciocinio += outro.raciocinio
        self.chamadas += outro.chamadas


@dataclass(frozen=True)
class RespostaModelo:
    texto: str
    chamadas: tuple[ChamadaFerramenta, ...]
    uso: Uso


class ErroProvedor(Exception):
    """Falha ao falar com o LLM. A mensagem para o cliente é segura; o detalhe vai pro log."""

    def __init__(self, codigo: str, mensagem_usuario: str):
        super().__init__(codigo)
        self.codigo = codigo
        self.mensagem_usuario = mensagem_usuario


class Turno:
    """Uma rodada de conversa com o modelo (da mensagem do cliente até a resposta final)."""

    def iniciar(self, mensagen: list[Mensagem]) -> RespostaModelo:
        raise NotImplementedError

    def continuar(self, resultados: list[ResultadoFerramenta]) -> RespostaModelo:
        raise NotImplementedError


class Provedor:
    def abrir_turno(self, instrucoes: str, ferramentas: list[dict]) -> Turno:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# OpenAI (Responses API)
# ---------------------------------------------------------------------------
MSG_INDISPONIVEL = "O assistente está indiponível no momento. Tente novamente em instantes."
MSG_OCUPADO = "O assistente está com muitas solicitações agora. Tente novamente em instantes."


def _traduzir_erro(e: Exception) -> ErroProvedor:
    """Converte erros do SDK em ErroProvedor. O detalhe técnico só vai para o log."""
    if isinstance(e, openai.APITimeoutError):
        codigo, msg = "TEMPO_ESGOTADO", "O assistente demorou demais para responder. Tente novamente em instantes."
    if isinstance(e, openai.APIConnectionError):
       codigo, msg = "SEM_CONEXAO", MSG_INDISPONIVEL
    if isinstance(e, openai.AuthenticationError):
        codigo, msg = "CREDENCIAL_INVALIDA", MSG_INDISPONIVEL
    if isinstance(e, openai.NotFoundError):
        codigo, msg = "MODELO_NAO_ENCONTRADO", MSG_INDISPONIVEL
    if isinstance(e, openai.BadRequestError):
        codigo, msg = "REQUISICAO_INVALIDA", MSG_INDISPONIVEL
    if isinstance(e, openai.APIStatusError):
        codigo, msg = "PROVEDOR_INDISPONIVEL", MSG_INDISPONIVEL
    if isinstance(e, openai.RateLimitError):
        sem_credito = getattr(e,"code", None) == "insufficient_quota"
        codigo, msg = ("SEM_CREDITO", MSG_INDISPONIVEL) if sem_credito else ("LIMITE_DE_USO", MSG_OCUPADO)
    else:
        codigo, msg = "ERRO_PROVEDOR", MSG_INDISPONIVEL
    # No log: tipo, status e a mensagem do PROVEDOR (ajuda a achar, por ex., modelo errado).
    detalhe = "" if codigo == "CREDENCIAL_INVALIDA" else str(getattr(e, "message", ""))[:200]
    log.warning("provedor falhou codigo=%s tipo=%s status=%s detalhe=%r", codigo, type(e).__name__,
                getattr(e, "status_code", None), detalhe)
    return ErroProvedor(codigo, msg)


def _uso_de(resposta) -> Uso:
    u = getattr(resposta, "usage", None)
    if u is None:
        return Uso(chamadas=1)
    cache = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
    pensando = getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0
    return Uso(entrada=u.input_tokens or 0, saida=u.output_tokens or 0,
               em_cache=cache, raciocinio=pensando, chamadas=1)


class _TurnoOpenAI(Turno):
    def __init__(self, provedor: "ProvedorOpenAI", instrucoes: str, ferramentas: list[dict]):
        self._p = provedor
        self._instrucoes = instrucoes
        self._ferramentas = ferramentas
        self._ultimo_id = None      # a Responses API encadeia as chamadas do turno por este id

    def iniciar(self, mensagens: list[Mensagem]) -> RespostaModelo:
        entrada = [{"role": m.papel, "content": m.texto} for m in mensagens]
        return self._chamar(entrada)

    def continuar(self, resultados: list[ResultadoFerramenta]) -> RespostaModelo:
        entrada = [{"type": "function_call_output", "call_id": r.chamada_id, "output": r.conteudo}
                   for r in resultados]
        return self._chamar(entrada)

    def _chamar(self, entrada: list[dict]) -> RespostaModelo:
        pedido = dict(
            model=self._p._modelo,
            instructions=self._instrucoes,      # não é herdado pelo encadeamento: vai a cada chamada
            input=entrada,
            tools=self._ferramentas,
            max_output_tokens=MAX_SAIDA,
        )
        if self._ultimo_id:
            pedido["previous_response_id"] = self._ultimo_id
        try:
            resp = self._p._cliente.responses.create(**pedido)
        except openai.OpenAIError as e:
            raise _traduzir_erro(e) from None
        self._ultimo_id = resp.id

        chamadas = tuple(ChamadaFerramenta(id=i.call_id, nome=i.name, argumentos_json=i.arguments)
                         for i in resp.output if i.type == "function_call")
        texto = resp.output_text or ""
        if resp.status == "incomplete" and not chamadas and not texto.strip():
            log.warning("resposta incompleta: %s", getattr(resp.incomplete_details, "reason", None))
            raise ErroProvedor("RESPOSTA_INCOMPLETA", MSG_INDISPONIVEL)
        return RespostaModelo(texto=texto, chamadas=chamadas, uso=_uso_de(resp))


class ProvedorOpenAI(Provedor):
    def __init__(self, api_key: str, modelo: str, timeout: float = 30.0, cliente=None):
        # 'cliente' existe para os testes injetarem um cliente com transporte falso.
        self._cliente = cliente or openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self._modelo = modelo

    def abrir_turno(self, instrucoes: str, ferramentas: list[dict]) -> Turno:
        # Nossas especificações são (nome, descrição, parâmetros); a OpenAI quer a forma "achatada".
        tools = [{"type": "function", "name": f["name"], "description": f["description"],
                  "parameters": f["parameters"], "strict": False} for f in ferramentas]
        return _TurnoOpenAI(self, instrucoes, tools)


def criar_provedor(cfg) -> Provedor | None:
    """Monta o provedor a partir da configuração; None se faltar chave ou modelo."""
    if not cfg.get("LLM_API_KEY") or not cfg.get("LLM_MODEL"):
        return None
    return ProvedorOpenAI(cfg["LLM_API_KEY"], cfg["LLM_MODEL"], timeout=cfg["LLM_TIMEOUT"])
