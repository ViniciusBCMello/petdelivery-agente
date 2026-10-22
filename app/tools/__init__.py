"""
Ferramentas do agente.

Importar este pacote registra todas as ferramentas em REGISTRO.
"""

from .base import REGISTRO, Contexto, ErroFerramenta, especificacoes, executar #noqa : F401
from . import catalogo, lojas, agenda, cliente, pedidos  # noqa: F401