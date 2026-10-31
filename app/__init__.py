from flask import Flask
from .config import Config
from .routes import bp
from .agente.historico import Historico
from .agente.orquestrador import Agente
from .agente.provedor import criar_provedor


def create_app():
    """
    Fábrica da aplicação: monta e devolve o objeto Flask configurado.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    # O agente de IA
    provedor = criar_provedor(app.config)
    if provedor is None:
        app.logger.warning("LLM_API_KEY ou LLM_MODEL ausente no .env: o chat não terá agente")
    app.extensions["agente"] = Agente(provedor, max_passos=app.config["AGENTE_MAX_PASSOS"]) if provedor else None
    app.extensions["historico"] = Historico(app.config["AGENTE_MAX_HISTORICO"])

    app.register_blueprint(bp)
    return app