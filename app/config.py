import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """
    Configurações da aplicação, todas vindas de variáveis de ambiente.
    """
    DEBUG = os.getenv("FLASK_DEBUG", "0") == 1
    
    # Limite do tamanho da mensagem do usuario.
    MAX_MENSAGEM = 1000

    # Banco de dados.
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_NAME = os.getenv("DB_NAME", "petdelivery")
    DB_USER = os.getenv("DB_USER", "petdelivery_app")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")