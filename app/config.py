import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    """
    Configurações da aplicação, todas vindas de variáveis de ambiente.
    """
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    
    # Limite do tamanho da mensagem do usuario.
    MAX_MENSAGEM = 1000

    # Banco de dados.
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_NAME = os.getenv("DB_NAME", "petdelivery")
    DB_USER = os.getenv("DB_USER", "petdelivery_app")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")


    # Chave que ASSINA o cookie da sessão. Sem SECRET_KEY no .env, usa uma chave aleatória
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True            # o JavaScript da pagina não le o cookie
    SESSION_COOKIE_SAMESITE = "Lax"           # o navegador não envia o cookie em requisições de outros sites
    SESSION_COOKIE_SECURE = False             # mude para True quando houver HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Agente de IA (provedor de LLM).
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "")
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))                # segundos por chamada ao provedor
    AGENTE_MAX_PASSOS = int(os.getenv("AGENTE_MAX_PASSOS", "6"))       # chamadas ao modelo por mensagem
    AGENTE_MAX_HISTORICO = int(os.getenv("AGENTE_MAX_HISTORICO", "12"))  # mensagens (só texto) lembradas
