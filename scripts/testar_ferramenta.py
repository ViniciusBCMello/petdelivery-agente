"""Executa UMA ferramenta direto, sem IA, para ver a entrada e a saida.

Uso (na raiz do projeto, com o .venv ativo):
    python scripts/testar_ferramenta.py --lista
    python scripts/testar_ferramenta.py listar_meus_pets --cliente=1     # simula o cliente logado
    python scripts/testar_ferramenta.py buscar_produtos termo="racao gatos"
    python scripts/testar_ferramenta.py consultar_estoque produto_id=9
    python scripts/testar_ferramenta.py consultar_estoque produto_id=9 loja_id=6
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from app.db import get_connection  # noqa: E402
from app.tools import Contexto, especificacoes, executar  # noqa: E402


def converter(texto):
    """'5' vira 5; qualquer outra coisa continua texto."""
    return int(texto) if texto.lstrip("-").isdigit() else texto


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--lista":
        print(json.dumps(especificacoes(), ensure_ascii=False, indent=2))
        return
    cliente_id, nome, argumentos = None, None, {}
    for a in args:
        if a.startswith("--cliente="):          # simula a SESSAO de login (nunca e argumento da ferramenta)
            cliente_id = int(a.split("=", 1)[1])
        elif nome is None:
            nome = a
        else:
            chave, _, valor = a.partition("=")
            argumentos[chave] = converter(valor)

    with create_app().app_context():
        conn = get_connection()
        try:
            resultado = executar(nome, argumentos, Contexto(conn=conn, cliente_id=cliente_id))
        finally:
            conn.close()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()