"""Conversa com o agente no terminal, sem navegador. Mostra as ferramentas usadas e os tokens.

Uso:
    python scripts/conversar.py --cliente=1
Digite a mensagem e Enter. Linha vazio ou 'sair' encerra o chat.
ATENÇÃO: usa a API de verdade, então cada mensagem gasta tokens.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app                                 # noqa: E402      
from app.agente.provedor import ErroProvedor, Mensagem     # noqa: E402
from app.db import get_connection                          # noqa: E402
from app.tools import Contexto                             # noqa: E402


def main():
    cliente_id = None
    for a in sys.argv[1:]:
        if a.startswith("--cliente="):          # simula a SESSÃO de login (nunca é argumento de ferramenta)
            cliente_id = int(a.split("=", 1)[1])

    app = create_app()
    agente = app.extensions["agente"]
    if agente is None:
        sys.exit("Configure LLM_API_KEY e LLM_MODEL no .env.")

    historico, total = [], 0
    with app.app_context():
        conn = get_connection()
        try:
            ctx = Contexto(conn=conn, cliente_id=cliente_id)
            while True:
                msg = input("\nvocê> ").strip()
                if not msg or msg.lower() == "sair":
                    break
                try:
                    r = agente.responder(historico, msg, ctx)
                except ErroProvedor as e:
                    print(f"[erro do provedor: {e.codigo}] {e.mensagem_usuario}")
                    continue
                historico += [Mensagem("user", msg), Mensagem("assistant", r.resposta)]
                total += r.uso.entrada + r.uso.saida
                print(f"\nPeteco> {r.resposta}")
                for c in r.chamadas:
                    print(f"   [ferramenta] {c.nome} -> {'ok' if c.ok else c.codigo_erro} ({c.ms} ms)")
                print(f"   [tokens] entrada={r.uso.entrada} (cache={r.uso.em_cache}) saida={r.uso.saida} "
                      f"passos={r.passos} | total da conversa={total}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()