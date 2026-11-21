"""
Orquestrador: conduz UM turno, da mensagem do cliente até a resposta final.

    cliente -> [modelo] -> pede ferramenta -> executar() valida e roda -> [modelo] -> ... -> texto

O modelo DECIDE qual ferramenta quer; quem valida e executa é a aplicação (executar).
Tudo que o modelo manda é tratado como não confiável. O laço tem limites para não girar
para sempre nem gastar tokens sem controle.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from app.tools import especificacoes, executar

from .prompt import INSTRUCOES, bloco_de_contexto
from .provedor import Mensagem, ResultadoFerramenta, Uso

log = logging.getLogger("agente.orquestrador")

MAX_CHARS_RESULTADO = 20000     # resultado maior que isso não é enviado ao modelo
MSG_SEM_RESPOSTA = "Não consegui montar uma resposta agora. Pode reformular a pergunta?"
MSG_LIMITE = ("Precisei de passos demais para responder e parei por segurança. "
              "Pode tentar de novo, de forma mais simples?")


@dataclass
class ChamadaRegistrada:
    """O que o agente fez, para depuração e (no Passo 9) para o log de auditoria."""
    nome: str
    ok: bool
    codigo_erro: str | None
    ms: int


@dataclass
class Resultado:
    resposta: str
    chamadas: list[ChamadaRegistrada] = field(default_factory=list)
    uso: Uso = field(default_factory=Uso)
    passos: int = 0                  # quantas vezes o modelo foi chamado
    interrompido: bool = False       # True se parou por limite de passos
    response_id: str | None = None


def _erro(codigo: str, mensagem: str) -> dict:
    return {"ok": False, "erro": {"codigo": codigo, "mensagem": mensagem}}


class Agente:
    def __init__(self, provedor, max_passos: int = 6, max_chamadas: int = 8,
                 executor=executar, agora=datetime.now):
        self._provedor = provedor
        self._max_passos = max_passos          # no máximo N chamadas ao modelo por mensagem
        self._max_chamadas = max_chamadas      # no máximo N ferramentas executadas por mensagem
        self._executor = executor
        self._agora = agora

    def responder(
        self,
        historico: list[Mensagem],
        mensagem: str,
        ctx,
        previous_response_id: str | None = None,
    ) -> Resultado:
        """Devolve a resposta ao cliente preservando a continuidade da Responses API."""
    
        pergunta = bloco_de_contexto(self._agora()) + mensagem
    
        turno = self._provedor.abrir_turno(
            INSTRUCOES,
            especificacoes(),
            previous_response_id=previous_response_id,
        )
    
        resultado = Resultado(resposta="")
    
        # Se existe uma resposta anterior, ela já contém o histórico completo
        # da cadeia. Enviamos somente a nova mensagem do usuário.
        if previous_response_id:
            mensagens = [Mensagem("user", pergunta)]
    
            log.info(
                "iniciando conversa encadeada | previous_response_id_presente=True"
            )
    
        else:
            # Fallback para histórico textual quando não existe ID anterior.
            mensagens = list(historico) + [Mensagem("user", pergunta)]
    
            log.info(
                "iniciando conversa pelo histórico textual | "
                "previous_response_id_presente=False"
            )
    
        resposta = turno.iniciar(mensagens)
    
        while True:
            resultado.passos += 1
            resultado.uso.somar(resposta.uso)
    
            if not resposta.chamadas:
                # Resposta final: guarda o ID da última resposta da API.
                resultado.resposta = (
                    resposta.texto.strip() or MSG_SEM_RESPOSTA
                )
    
                resultado.response_id = resposta.response_id
    
                break
            
            if resultado.passos >= self._max_passos:
                log.warning(
                    "turno interrompido: limite de %d passos",
                    self._max_passos,
                )
    
                resultado.resposta = MSG_LIMITE
                resultado.interrompido = True
    
                # Não persiste uma cadeia que terminou com chamadas pendentes.
                resultado.response_id = None
    
                break
            
            envios = [
                self._executar_uma(c, ctx, resultado)
                for c in resposta.chamadas
            ]
    
            # Continua a cadeia interna de chamadas de ferramentas.
            resposta = turno.continuar(envios)
    
        log.info(
            "turno passos=%d ferramentas=%d tokens_entrada=%d "
            "tokens_saida=%d interrompido=%s response_id_presente=%s",
            resultado.passos,
            len(resultado.chamadas),
            resultado.uso.entrada,
            resultado.uso.saida,
            resultado.interrompido,
            resultado.response_id is not None,
        )
    
        return resultado

    def _executar_uma(self, chamada, ctx, resultado: Resultado) -> ResultadoFerramenta:
        inicio = time.perf_counter()
        if len(resultado.chamadas) >= self._max_chamadas:
            envelope = _erro("LIMITE_DE_CHAMADAS", "Limite de consultas por mensagem atingido.")
        else:
            try:
                argumentos = json.loads(chamada.argumentos_json or "{}")
            except (json.JSONDecodeError, TypeError):
                envelope = _erro("PARAMETRO_INVALIDO", "Os argumentos não são um JSON válido.")
            else:
                try:
                    envelope = self._executor(chamada.nome, argumentos, ctx)
                except Exception:       # executar() não levanta; isto protege contra um executor defeituoso
                    log.exception("executor falhou ferramenta=%s", chamada.nome)
                    envelope = _erro("ERRO_INTERNO", "Ocorreu um erro inesperado ao executar a ferramenta.")

        conteudo = json.dumps(envelope, ensure_ascii=False, default=str)
        if len(conteudo) > MAX_CHARS_RESULTADO:
            envelope = _erro("RESULTADO_GRANDE_DEMAIS", "O resultado é grande demais; use um filtro mais específico.")
            conteudo = json.dumps(envelope, ensure_ascii=False)

        erro = envelope.get("erro") or {}
        resultado.chamadas.append(ChamadaRegistrada(
            nome=str(chamada.nome), ok=bool(envelope.get("ok")), codigo_erro=erro.get("codigo"),
            ms=round((time.perf_counter() - inicio) * 1000)))
        return ResultadoFerramenta(chamada.id, conteudo)