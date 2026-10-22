import mysql.connector

from app.tools import REGISTRO, especificacoes, executar


def test_ferramenta_desconhecida(ctx):
    r = executar("apagar_tudo", {}, ctx)
    assert not r["ok"] and r["erro"]["codigo"] == "FERRAMENTA_DESCONHECIDA"


def test_parametro_inventado_pelo_modelo_e_rejeitado(ctx):
    r = executar("buscar_produtos", {"termo": "racao", "sql": "DROP TABLE produto"}, ctx)
    assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO"
    assert "sql" in r["erro"]["mensagem"]


def test_parametro_obrigatorio_ausente(ctx):
    for args in ({}, None, {"termo": None}):
        r = executar("buscar_produtos", args, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO"


def test_argumentos_que_nao_sao_objeto(ctx):
    for args in ("racao", ["racao"], 42):
        r = executar("buscar_produtos", args, ctx)
        assert not r["ok"] and r["erro"]["codigo"] == "PARAMETRO_INVALIDO"


def test_falha_do_banco_vira_erro_controlado(ctx, monkeypatch):
    def quebrado(*a, **k):
        raise mysql.connector.errors.OperationalError("banco fora do ar (simulado)")
    monkeypatch.setattr(ctx.conn, "cursor", quebrado)
    r = executar("buscar_produtos", {"termo": "racao"}, ctx)
    assert not r["ok"] and r["erro"]["codigo"] == "SERVICO_INDISPONIVEL"
    assert "simulado" not in r["erro"]["mensagem"]          # detalhe tecnico nao vaza


def test_erro_inesperado_vira_erro_interno(ctx, monkeypatch):
    def explode(*a, **k):
        raise RuntimeError("bug simulado")
    monkeypatch.setattr(ctx.conn, "cursor", explode)
    r = executar("consultar_estoque", {"produto_id": 1}, ctx)
    assert not r["ok"] and r["erro"]["codigo"] == "ERRO_INTERNO"
    assert "bug" not in r["erro"]["mensagem"]


def test_executar_nunca_levanta_excecao(ctx):
    entradas = [("buscar_produtos", {"termo": object()}), ("consultar_estoque", {"produto_id": {}}),
                ("", {}), (None, {})]
    for nome, args in entradas:
        assert "ok" in executar(nome, args, ctx)


def test_especificacoes_estao_completas():
    specs = {s["name"]: s for s in especificacoes()}
    assert set(specs) == set(REGISTRO) and {"buscar_produtos", "consultar_estoque"} <= set(specs)
    for s in specs.values():
        assert len(s["description"]) > 30
        esquema = s["parameters"]
        assert esquema["type"] == "object" and esquema["additionalProperties"] is False
        assert set(esquema["required"]) <= set(esquema["properties"])
    assert specs["consultar_estoque"]["parameters"]["required"] == ["produto_id"]
