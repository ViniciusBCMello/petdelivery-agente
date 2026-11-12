"""Memória curta da conversa: só texto, com limites."""
from app.agente.historico import Historico
from app.agente.provedor import Mensagem


def test_comeca_vazio_e_guarda_pergunta_e_resposta():
    h = Historico()
    assert h.obter("a") == []
    h.registrar("a", "oi", "olá")
    assert h.obter("a") == [Mensagem("user", "oi"), Mensagem("assistant", "olá")]


def test_conversas_sao_separadas():
    h = Historico()
    h.registrar("1:x", "pergunta do 1", "r1")
    h.registrar("2:y", "pergunta do 2", "r2")
    assert [m.texto for m in h.obter("1:x")] == ["pergunta do 1", "r1"]
    assert [m.texto for m in h.obter("2:y")] == ["pergunta do 2", "r2"]


def test_corta_nas_ultimas_mensagens_sempre_comecando_pela_pergunta():
    h = Historico(max_mensagens=4)
    for i in range(5):
        h.registrar("a", f"p{i}", f"r{i}")
    lista = h.obter("a")
    assert [m.texto for m in lista] == ["p3", "r3", "p4", "r4"]
    assert lista[0].papel == "user"


def test_limite_impar_e_arredondado_para_par():
    h = Historico(max_mensagens=5)
    for i in range(4):
        h.registrar("a", f"p{i}", f"r{i}")
    assert len(h.obter("a")) == 4 and h.obter("a")[0].papel == "user"


def test_descarta_a_conversa_mais_antiga_quando_passa_do_limite():
    h = Historico(max_conversas=2)
    h.registrar("a", "1", "1")
    h.registrar("b", "2", "2")
    h.registrar("a", "3", "3")          # 'a' voltou a ser a mais recente
    h.registrar("c", "4", "4")          # estoura: sai a mais antiga, que agora é 'b'
    assert h.obter("b") == [] and h.obter("a") and h.obter("c")


def test_obter_devolve_copia():
    h = Historico()
    h.registrar("a", "oi", "olá")
    h.obter("a").append(Mensagem("user", "intruso"))
    assert len(h.obter("a")) == 2


def test_limpar_esquece_so_aquela_conversa():
    h = Historico()
    h.registrar("a", "1", "1")
    h.registrar("b", "2", "2")
    h.limpar("a")
    h.limpar("nao-existe")                  # não levanta erro
    assert h.obter("a") == [] and len(h.obter("b")) == 2