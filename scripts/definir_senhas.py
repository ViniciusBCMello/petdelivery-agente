"""Define a senha de DEMONSTRAÇÃO dos clientes sintéticos (só para a demonstração local).

Uso (na raiz do projeto, com o .venv ativo):
    python scripts/definir_senhas.py                 # quem ainda nao tem senha recebe a senha padrao
    python scripts/definir_senhas.py --todos         # redefine a senha de todos
    python scripts/definir_senhas.py --senha outra   # escolhe a senha de demonstracao

Guarda só o HASH da senha (nunca a senha). Rode de novo depois de
"popular_dados.py --reset", porque o reset apaga os clientes.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mysql.connector  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

from app.config import Config  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Define a senha de demonstracao dos clientes.")
    ap.add_argument("--senha", default="pet123", help="senha de demonstracao (padrao: pet123)")
    ap.add_argument("--todos", action="store_true", help="redefine tambem quem ja tem senha")
    args = ap.parse_args()

    if "agente" not in Config.DB_NAME:
        sys.exit(f"Por seguranca, este script so roda em banco com 'agente' no nome (DB_NAME={Config.DB_NAME}).")

    conn = mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT, database=Config.DB_NAME,
                                   user=Config.DB_USER, password=Config.DB_PASSWORD, charset="utf8mb4")
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM cliente" + ("" if args.todos else " WHERE senha_hash IS NULL") + " ORDER BY id")
        ids = [linha[0] for linha in cur.fetchall()]
        for cliente_id in ids:                       # um hash por cliente (cada um com o seu "sal")
            cur.execute("UPDATE cliente SET senha_hash = %s WHERE id = %s",
                        (generate_password_hash(args.senha), cliente_id))
        conn.commit()
        print(f"Senha definida para {len(ids)} cliente(s).")
        print(f"\nSenha de demonstracao: {args.senha}\nExemplos de login (e-mail):")
        cur.execute("SELECT id, nome, email FROM cliente ORDER BY id LIMIT 5")
        for cid, nome, email in cur.fetchall():
            print(f"  cliente {cid}: {email}   ({nome})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()