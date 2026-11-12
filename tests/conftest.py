"""Fixtures dos testes. Estes testes leem o banco POPULADO por scripts/popular_dados.py
(dados deterministicos) e nao alteram nada nele."""
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.db import get_connection
from app.tools import Contexto, executar
from app.tools.confirmacao import Confirmacoes


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


@pytest.fixture()
def como_cliente(ctx):
    """Devolve um Contexto logado como o cliente pedido (simula a sessao de login)."""
    def _como(cliente_id):
        return Contexto(conn=ctx.conn, cliente_id=cliente_id)
    return _como

# ---------------------------------------------------------------------------
# Testes de ESCRITA: gravam de verdade, mas nada fica no banco depois do teste.
# ---------------------------------------------------------------------------
class ConexaoReversivel:
    """Envolve uma conexão real. commit() vira um SAVEPOINT e rollback() volta ao último;
    desfazer() descarta tudo. Assim as ferramentas rodam o código de produção (commit/rollback)
    sem sujar os dados de demonstração."""

    def __init__(self, conn):
        self._c = conn
        self._n = 0
        self._fixados = 0
        self._ponto()

    def _ponto(self):
        cur = self._c.cursor()
        cur.execute(f"SAVEPOINT sp{self._n}")
        cur.close()

    @property
    def commits(self):
        """Quantos commits as ferramentas fizeram (sem commit, em produção a gravação se perderia)."""
        return self._n - self._fixados

    def fixar(self):
        """Marca o estado atual como ponto de retorno (o preparo do teste sobrevive a um rollback da ferramenta),
        sem contar como commit."""
        self._n += 1
        self._fixados += 1
        self._ponto()

    def commit(self):
        self._n += 1
        self._ponto()

    def rollback(self):
        cur = self._c.cursor()
        cur.execute(f"ROLLBACK TO SAVEPOINT sp{self._n}")
        cur.close()

    def desfazer(self):
        self._c.rollback()

    def close(self):          # a rota fecha a conexão ao fim da requisição; aqui quem fecha é a fixture
        pass

    def __getattr__(self, nome):          # cursor(), close()... vão direto para a conexão real
        return getattr(self._c, nome)


class Relogio:
    """Relógio controlável do cofre de confirmações."""

    def __init__(self):
        self.agora = datetime(2026, 1, 1, 12, 0)

    def __call__(self):
        return self.agora

    def avancar(self, **kw):
        self.agora += timedelta(**kw)


class Ambiente:
    """Contextos de escrita que compartilham a mesma conexão reversível e o mesmo cofre."""

    def __init__(self, conn, cofre, relogio):
        self.conn, self.cofre, self.relogio = conn, cofre, relogio

    def como(self, cliente_id, turno=1):
        return Contexto(conn=self.conn, cliente_id=cliente_id, confirmacoes=self.cofre, turno=turno)

    def sql(self, consulta, params=()):
        cur = self.conn.cursor()
        cur.execute(consulta, params)
        linhas = cur.fetchall()
        cur.close()
        return linhas


@pytest.fixture()
def escrita(app):
    with app.app_context():
        real = get_connection()
        conn = ConexaoReversivel(real)
        relogio = Relogio()
        try:
            yield Ambiente(conn, Confirmacoes(agora=relogio), relogio)
        finally:
            conn.desfazer()
            real.close()