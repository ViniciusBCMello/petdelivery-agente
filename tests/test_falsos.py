"""Dublês de teste do agente: um provedor de LLM que segue um ROTEIRO, sem rede e sem custo."""
from app.agente.provedor import ChamadaFerramenta, Provedor, RespostaModelo, Turno, Uso


def texto(t, entrada=100, saida=10):
    """Resposta do modelo que é só texto (fim do turno)."""
    return RespostaModelo(texto=t, chamadas=(), uso=Uso(entrada=entrada, saida=saida, chamadas=1))


def chama(*pedidos, entrada=100, saida=10):
    """Resposta do modelo pedindo ferramentas. Cada pedido é (id, nome, argumentos_json)."""
    cs = tuple(ChamadaFerramenta(id=i, nome=n, argumentos_json=a) for i, n, a in pedidos)
    return RespostaModelo(texto="", chamadas=cs, uso=Uso(entrada=entrada, saida=saida, chamadas=1))


class ProvedorFalso(Provedor):
    """Entrega as respostas do roteiro, na ordem, e guarda tudo que o orquestrador enviou."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.instrucoes = []        # instruções recebidas em cada abrir_turno
        self.ferramentas = []
        self.iniciais = []          # mensagens enviadas em cada iniciar()
        self.envios = []            # resultados de ferramenta enviados em cada continuar()

    def abrir_turno(self, instrucoes, ferramentas):
        self.instrucoes.append(instrucoes)
        self.ferramentas.append(ferramentas)
        return _TurnoFalso(self)


class _TurnoFalso(Turno):
    def __init__(self, provedor):
        self._p = provedor

    def _proxima(self):
        item = self._p.roteiro.pop(0)
        if callable(item):                      # função(provedor) -> resposta: usa o que já foi recebido
            item = item(self._p)
        if isinstance(item, Exception):         # o roteiro também pode simular falhas
            raise item
        return item

    def iniciar(self, mensagens):
        self._p.iniciais.append(list(mensagens))
        return self._proxima()

    def continuar(self, resultados):
        self._p.envios.append(list(resultados))
        return self._proxima()


class ProvedorSempreChama(Provedor):
    """Modelo 'travado': pede uma ferramenta para sempre (testa o limite de passos)."""

    def __init__(self):
        self.chamadas_ao_modelo = 0

    def abrir_turno(self, instrucoes, ferramentas):
        outer = self

        class T(Turno):
            def iniciar(self, mensagens):
                outer.chamadas_ao_modelo += 1
                return chama(("c", "listar_categorias", "{}"))

            def continuar(self, resultados):
                outer.chamadas_ao_modelo += 1
                return chama(("c", "listar_categorias", "{}"))
        return T()