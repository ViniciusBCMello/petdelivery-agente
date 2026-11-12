"""
Confirmação em duas etapas para ferramentas que GRAVAM no banco.

1 - O modelo chama a ferramenta SEM "confirmação": nada é gravado no banco. Retornado um resumo e um código do pedido.
2 - O cliente lê o resumo e responde uma NOVA mensagem.
3 - O modelo faz a chamada novamente com o mesmos parâmetros e o código: agora grava. 

Quem emite e confere o código é a aplicação, não o modelo. O código:
- é do cliente logado e de UMA ação (agendar, cancelar...);
- vale para os parâmetros exatos do resumo;
- expira(10 min) e só serve uma vez;
- só pode ser usado em um turno POSTERIOR ao que o emitiu. Sem isso o modelo poderia
pedir o resumo e confirmar na mesma hora, sem o cliente ter aprovado nada
"""
from datetime import datetime, timedelta
from app.tools.base import ErroFerramenta, exigir_texto
from dataclasses import dataclass
import json
import itertools
import threading
import secrets


VALIDADE = timedelta(minutes=10)
MAX_PENDENTES = 500


@dataclass
class _Pendente:
    cliente_id: int
    acao: str
    params: str         # paramêtros em forma canônica. (JSON ordenado)
    turno: int          # turno em que o código foi emitido.
    expira_em: datetime


def _canonico(params: dict) -> str:
    return json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)


class Confirmacoes:
    """Cofre em memória dos códigos pendente( um por processo)"""
    def __init__(self, validade: timedelta = VALIDADE, agora=datetime.now, limite: int = MAX_PENDENTES):
        self._validade = validade
        self._agora = agora
        self._limite = limite
        self._pendentes: dict[str, _Pendente] = {}
        self._turnos = itertools.count(1)
        self._trava = threading.Lock()      # ação que trava para evitar concorrência; sincronização


    def proximo_turno(self) -> int:
        """Número crescente: um por mensagem do cliente."""
        with self._trava:
            return next(self._turnos)


    def emitir(self, cliente_id: int, acao: str, params: dict, turno: int) -> str:
        with self._trava:       # executa o código dentro do bloqueio e libera ao terminar.
            agora = self._agora()
            for key in [key for key, pendente in self._pendentes.items() if pendente.expira_em <= agora]:
                del self._pendentes[key]
            while len(self._pendentes) >= self._limite:
                del self._pendentes[next(iter(self._pendentes))]    # descarta o mais antigo
            codigo = secrets.token_hex(3).upper()
            while codigo in self._pendentes:
                codigo = secrets.token_hex(3).upper()
            self._pendentes[codigo] = _Pendente(cliente_id, acao, _canonico(params),turno, agora + self._validade)      # registro no dicionário.
            return codigo


    def consumir(self, codigo: str, cliente_id: int, acao: str, params: dict, turno: int) -> None:
        """Confere e GASTA o código. Levanta ErroFerramenta se algo não bater."""
        with self._trava:
            p = self._pendentes.get(codigo.strip().upper())
            invalido = ErroFerramenta(
                "CONFIRMACAO_INVALIDA",
                "Código de confimação inválido, expirado ou já usado. Chame a ferramenta de novo, sem 'confirmacao', para obter um resumo e um código novo." 
            )
            # Código de outro cliente ou de outra ação é tratado como inexistente.
            if p is None or p.cliente_id != cliente_id or p.acao != acao:
                raise invalido
            if p.expira_em <= self._agora():
                del self._pendentes[codigo.strip().upper()]
                raise invalido
            if turno <= p.turno:
                raise ErroFerramenta(
                    "CONFIRMACAO_PREMATURA",
                    "A confirmação precisa vir do cliente em uma NOVA mensagem. Mostre ao cliente o resumo e peça confirmação."
                )
            if p.params != _canonico(params):
                raise ErroFerramenta(
                    "CONFIRMACAO_DIFERENTE",
                    "Os parâmetros são diferentes dos que foram mostrados ao cliente."
                )
            del self._pendentes[codigo.strip().upper()]


def _cofre(ctx) -> Confirmacoes:
    if ctx.confirmacoes is None:
        raise ErroFerramenta("CONFIRMACAO_INDISPONIVEL","A confirmação de ações não está disponível neste ambiente.")
    return ctx.confirmacoes


def propor(ctx, cliente_id: int, acao: str, params: dict, resumo: dict) -> dict:
    """É a primeira etapa.
    Não grava nada; devolve o resumo e o código que o cliente precisa conferir.
    """
    codigo = _cofre(ctx).emitir(cliente_id, acao, params, ctx.turno)
    return {
        "gravado": False,
        "requer_confirmacao": True,
        "codigo_confirmacao": codigo,
        "validade_minutos": int(VALIDADE.total_seconds() // 60),
        "resumo": resumo,
        "instrucao": ("Nada foi gravado ainda. Mostre o resumo ao cliente e pergunte se conmfirma."
                      "Só depois que o cliente responder em NOVA mensagem, chame esta ferramenta de novo"
                      f"com os MESMOS parâmetros e confirmacao='{codigo}'."),
    }


def conferir(ctx, cliente_id: int, acao: str, params: dict, codigo) -> None:
    """É a segunda etapa.
    confere e gasta o código. Chame só depois de validar as regras de negócio
    """
    codigo = exigir_texto(codigo, "confirmacao", max_len=30)
    _cofre(ctx).consumir(codigo, cliente_id, acao, params, ctx.turno)