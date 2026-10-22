from flask import Flask
from .config import Config
from .routes import bp


def create_app():
    """
    Fábrica da aplicação: monta e devolve o objeto Flask configurado.
    """
    app = Flask(__name__)
    app.config.from_object(Config)

    app.register_blueprint(bp)
    return app