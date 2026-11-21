"""
Histórico de conversas.

Mantém:
- Histórico textual como alternativa.
- ID da última resposta da Responses API para continuidade nativa.
- Estado separado por conversa.

Os resultados das ferramentas permanecem armazenados na cadeia da Responses API,
não precisam ser copiados manualmente para o histórico textual.
"""
import threading
from collections import OrderedDict

from .provedor import Mensagem


class Historico:
    def __init__(self, max_mensagens: int = 12, max_conversas: int = 200):
        self._max_mensagens = max(2, max_mensagens - max_mensagens % 2)
        self._max_conversas = max_conversas

        self._conversas: OrderedDict[str, list[Mensagem]] = OrderedDict()
        self._response_ids: dict[str, str] = {}

        self._trava = threading.Lock()

    def obter(self, chave: str) -> list[Mensagem]:
        """Retorna uma cópia do histórico textual."""
        with self._trava:
            return list(self._conversas.get(chave, []))

    def obter_response_id(self, chave: str) -> str | None:
        """Retorna o ID da última resposta da Responses API."""
        with self._trava:
            return self._response_ids.get(chave)

    def registrar(
        self,
        chave: str,
        pergunta: str,
        resposta: str,
        response_id: str | None = None,
    ) -> None:
        """Registra a conversa e atualiza o ID da última resposta."""
        with self._trava:
            lista = self._conversas.pop(chave, [])

            lista += [
                Mensagem("user", pergunta),
                Mensagem("assistant", resposta),
            ]

            self._conversas[chave] = lista[-self._max_mensagens:]

            if response_id:
                self._response_ids[chave] = response_id
            else:
                # Sem ID válido, a próxima interação usará o histórico textual.
                self._response_ids.pop(chave, None)

            while len(self._conversas) > self._max_conversas:
                removida, _ = self._conversas.popitem(last=False)
                self._response_ids.pop(removida, None)

    def limpar(self, chave: str) -> None:
        """Esquece somente a conversa informada."""
        with self._trava:
            self._conversas.pop(chave, None)
            self._response_ids.pop(chave, None)
