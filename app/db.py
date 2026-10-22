import mysql.connector
from flask import current_app


def get_connection():
    """Abre uma conexao nova com o MySQL, usando as configuracoes do app.

    Quem chamar é responsavel por fechar (conn.close()).
    """
    cfg = current_app.config
    return mysql.connector.connect(
        host=cfg["DB_HOST"],
        port=cfg["DB_PORT"],
        database=cfg["DB_NAME"],
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
        charset="utf8mb4",
        connection_timeout=5,
    )