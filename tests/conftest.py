"""Fixtures dos testes. Estes testes leem o banco POPULADO por scripts/popular_dados.py
(dados deterministicos) e nao alteram nada nele."""
import pytest

from app import create_app
from app.db import get_connection
from app.tools import Contexto, executar


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture()
def ctx(app):
    with app.app_context():
        conn = get_connection()
        try:
            yield Contexto(conn=conn)
        finally:
            conn.close()


@pytest.fixture()
def achar_produto(ctx):
    """Devolve o id de um produto ATIVO a partir do nome exato."""
    def _achar(nome):
        r = executar("buscar_produtos", {"termo": nome}, ctx)
        assert r["ok"], r
        ids = [p["id"] for p in r["dados"]["produtos"] if p["nome"] == nome]
        assert ids, f"produto '{nome}' nao encontrado (rode scripts/popular_dados.py --reset)"
        return ids[0]
    return _achar
