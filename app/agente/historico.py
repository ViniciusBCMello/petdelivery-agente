"""
Memória curta da conversa: só o TEXTO do que o cliente disse e do que o agente respondeu.

Resultados de ferramentas NÃO entram: o que vale numa conversa (estoque, horário) pode
mudar em minutos, e guardá-los só aumentaria o custo. Se o cliente voltar ao assunto, o
agente consulta de novo.

Fica na memória do processo (demonstração local): reiniciar o servidor esquece tudo.
A versão persistente (tabelas conversa/mensagem) entra junto com o log de auditoria.
"""
import threading
from collections import OrderedDict

from .provedor import Mensagem


class Historico:
    def __init__(self, max_mensagens: int = 12, max_conversas: int = 200):
        self._max_mensagens = max(2, max_mensagens - max_mensagens % 2)   # par: sempre pergunta + resposta
        self._max_conversas = max_conversas
        self._conversas: OrderedDict[str, list[Mensagem]] = OrderedDict()
        self._trava = threading.Lock()      # o servidor do Flask atende várias requisições ao mesmo tempo

    def obter(self, chave: str) -> list[Mensagem]:
        with self._trava:
            return list(self._conversas.get(chave, []))     # cópia: quem recebe não altera o original

    def registrar(self, chave: str, pergunta: str, resposta: str) -> None:
        with self._trava:
            lista = self._conversas.pop(chave, [])
            lista += [Mensagem("user", pergunta), Mensagem("assistant", resposta)]
            self._conversas[chave] = lista[-self._max_mensagens:]   # fica no fim = mais recente
            while len(self._conversas) > self._max_conversas:
                self._conversas.popitem(last=False)                 # descarta a conversa mais antiga

    def limpar(self, chave: str) -> None:
        with self._trava:
            self._conversas.pop(chave, None)