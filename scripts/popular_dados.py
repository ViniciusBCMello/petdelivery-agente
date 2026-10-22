"""Passo 2.4: popula o banco do agente com dados FICTICIOS.

Uso (na raiz do projeto, com o .venv ativo):
    python scripts/popular_dados.py                 # popula (so se o banco estiver vazio)
    python scripts/popular_dados.py --reset         # apaga tudo e popula de novo
    python scripts/popular_dados.py --hoje 2026-10-05   # fixa a data de referencia

Garantias de privacidade (os dados sao todos inventados):
  - nomes sao combinacoes aleatorias de nomes e sobrenomes comuns;
  - CPFs tem digito verificador INVALIDO de proposito (nunca batem com pessoa real);
  - e-mails usam o dominio reservado example.com;
  - telefones usam a faixa 90000-xxxx, que nao e atribuida a linhas moveis.

O gerador e deterministico: rodar duas vezes gera exatamente os mesmos dados
(a unica coisa que muda e a data de referencia "hoje").

Casos de teste embutidos para o agente:
  - "Nutrimax Gatos Filhotes" esta em falta em TODAS as lojas;
  - "Focinho Feliz Premium Gatos" so tem estoque na loja mais distante (Deodoro);
  - varios itens com estoque baixo (1 a 3 unidades) ou zerado;
  - horarios cancelados que foram reocupados por outro cliente;
  - pedidos em todos os status; pagamentos com tentativas recusadas;
  - pedidos antigos com preco menor que o preco atual do produto.
"""
import argparse
import math
import random
import sys
import unicodedata
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mysql.connector  # noqa: E402

from app.config import Config  # noqa: E402

# ---------------------------------------------------------------------------
# Estrutura das tabelas (ordem de insercao respeita as chaves estrangeiras)
# ---------------------------------------------------------------------------
COLUNAS = {
    "categoria": ["id", "nome"],
    "tipo": ["id", "nome"],
    "loja": ["id", "nome_fantasia", "cnpj", "endereco", "bairro", "cidade", "estado", "latitude", "longitude"],
    "bairro": ["id", "nome", "cidade", "estado", "latitude", "longitude"],
    "produto": ["id", "imagem", "nome", "preco", "ativo", "categoria_id", "tipo_id"],
    "item_estoque": ["id", "produto_id", "loja_id", "cor", "tamanho", "quantidade"],
    "animal": ["id", "especie", "raca", "idade", "nome", "peso"],
    "cliente": ["id", "nome", "cpf", "telefone", "email", "animal_id", "criado_em"],
    "endereco": ["id", "cliente_id", "rua", "numero", "complemento", "bairro", "cep", "cidade", "estado",
                 "latitude", "longitude"],
    "perfil_pet": ["id", "cliente_id", "animal_id"],
    "veterinario": ["id", "crmv", "nome", "especialidade", "loja_id"],
    "horario_atendimento": ["id", "veterinario_id", "dia_semana", "hora_inicio", "hora_fim"],
    "recepcionista": ["id", "cpf", "nome"],
    "entregador": ["id", "cpf", "nome", "cnh", "placa_veiculo"],
    "agendamento": ["id", "cliente_id", "animal_id", "veterinario_id", "recepcionista_id", "tipo", "data_hora",
                    "status", "observacao", "criado_em"],
    "pedido": ["id", "cliente_id", "loja_id", "entregador_id", "status", "codigo_transacao", "endereco_entrega",
               "data_finalizacao", "criado_em"],
    "itens_pedido": ["id", "pedido_id", "item_estoque_id", "quantidade", "preco_unitario"],
    "pagamento": ["id", "pedido_id", "id_pagamento", "aprovado", "criado_em"],
    "petshop": ["id", "imagem", "link_destino", "ativo"],
}
ORDEM = list(COLUNAS)

# ---------------------------------------------------------------------------
# Material para gerar os dados
# ---------------------------------------------------------------------------
PRIMEIROS = [
    "Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique", "Isabela", "João", "Karina",
    "Lucas", "Mariana", "Nicolas", "Olivia", "Paulo", "Queila", "Rafael", "Sofia", "Thiago", "Úrsula", "Vitor",
    "Wesley", "Yasmin", "Amanda", "Caio", "Daniela", "Elias", "Fernanda", "Gustavo", "Helena", "Igor", "Juliana",
    "Kleber", "Larissa", "Matheus", "Natália", "Otávio", "Patrícia", "Renato", "Sabrina", "Tatiane", "Vanessa",
    "Wagner", "Beatriz", "Cláudio", "Débora", "Eduardo", "Flávia", "Leandro", "Mônica", "Rodrigo",
]
SOBRENOMES = [
    "Almeida", "Barbosa", "Cardoso", "Dias", "Esteves", "Ferreira", "Gomes", "Henriques", "Ibrahim", "Jardim",
    "Lacerda", "Moreira", "Nascimento", "Oliveira", "Pereira", "Queiroz", "Ribeiro", "Santos", "Teixeira",
    "Uchoa", "Vasconcelos", "Xavier", "Zanetti", "Araújo", "Batista", "Campos", "Duarte", "Farias", "Guimarães",
    "Lopes", "Machado", "Neves", "Pinto", "Rocha", "Souza", "Tavares",
]
NOMES_PET = [
    "Max", "Luna", "Thor", "Mel", "Bob", "Nina", "Fred", "Lola", "Rex", "Mia", "Toby", "Bela", "Simba", "Amora",
    "Zeus", "Pipoca", "Nino", "Fiona", "Bruce", "Cacau", "Dory", "Bento", "Maya", "Apolo", "Jade", "Floquinho",
    "Princesa", "Marley", "Safira", "Tico", "Pretinha", "Docinho", "Ted", "Nala", "Duque", "Maggie", "Pingo",
    "Hulk", "Chloe", "Scooby", "Gaia", "Olavo", "Mingau", "Panda", "Estrela", "Biscoito", "Cleo", "Tom",
]
RACAS = {  # (raca, peso minimo kg, peso maximo kg)
    "cachorro": [("Vira-lata", 8, 30), ("Labrador", 25, 36), ("Golden Retriever", 25, 34), ("Poodle", 4, 10),
                 ("Shih Tzu", 4, 9), ("Pinscher", 3, 6), ("Bulldog Francês", 8, 14), ("Pitbull", 18, 32),
                 ("Pastor Alemão", 25, 40), ("Yorkshire", 2, 4), ("Spitz Alemão", 3, 7), ("Border Collie", 14, 22)],
    "gato": [("SRD", 3, 6), ("Siamês", 3, 5.5), ("Persa", 3.5, 7), ("Maine Coon", 5, 9), ("Angorá", 3, 5.5),
             ("Ragdoll", 4.5, 8)],
    "coelho": [("Mini Lop", 1.2, 2.6), ("Anão", 0.9, 1.8)],
}
IDADE_MAX = {"cachorro": 15, "gato": 17, "coelho": 8}

# Bairros do Rio (centro aproximado; coordenadas FICTICIAS para a demonstracao)
BAIRROS = {
    "Valqueire": (-22.8806, -43.3600), "Madureira": (-22.8727, -43.3375), "Tijuca": (-22.9246, -43.2420),
    "Olaria": (-22.8467, -43.2663), "Cachambi": (-22.8884, -43.2735), "Deodoro": (-22.8553, -43.3830),
    "Bangu": (-22.8786, -43.4655), "Méier": (-22.9019, -43.2776), "Penha": (-22.8431, -43.2761),
    "Campo Grande": (-22.9026, -43.5614), "Copacabana": (-22.9711, -43.1863),
    "Barra da Tijuca": (-23.0004, -43.3659), "Jacarepaguá": (-22.9368, -43.3496),
    "Realengo": (-22.8795, -43.4306), "Vila Isabel": (-22.9164, -43.2455), "Botafogo": (-22.9519, -43.1858),
}
RUAS = [
    "Rua das Acácias", "Rua dos Ipês", "Avenida das Palmeiras", "Rua Jasmim", "Rua das Orquídeas",
    "Travessa do Sol", "Rua Bem-te-vi", "Rua dos Girassóis", "Avenida Central", "Rua da Paz",
    "Rua das Mangueiras", "Rua Horizonte", "Rua Pardal", "Rua Aurora", "Travessa Lírio",
]

# Lojas (as 6 dos banners da vitrine); a primeira e a loja original do e-commerce
LOJAS = [
    ("Tudo Papet", "90.000.001/0001-00", "Rua Cardoso de Morais, 350", "Valqueire"),
    ("Dr Pet", "90.000.002/0001-00", "Rua das Acácias, 120", "Madureira"),
    ("Lily's Pet Shop", "90.000.003/0001-00", "Rua Jasmim, 88", "Tijuca"),
    ("Pethouse", "90.000.004/0001-00", "Avenida Central, 1500", "Olaria"),
    ("Osso Pet Shop", "90.000.005/0001-00", "Rua dos Ipês, 45", "Cachambi"),
    ("Amigão Pet Shop", "90.000.006/0001-00", "Rua Aurora, 700", "Deodoro"),
]
BANNERS = [
    ("tudopapet.png", "tudopapet"), ("drpet.png", "drpet"), ("lily.png", "lily"),
    ("pethouse.png", "pethouse"), ("osspet.png", "osspet"), ("amigaopet.png", "amigaopet"),
]

CATEGORIAS = ["Ração", "Medicamentos", "Higiene", "Acessórios", "Brinquedos"]
TIPOS = ["Filhote", "Adulto", "Antipulgas", "Sênior", "Vermífugo", "Higiene", "Acessório", "Brinquedo"]

# Os 4 produtos originais do e-commerce (mesmos precos e imagens)
PRODUTOS_ORIGINAIS = [
    (1, "37.png", "Royal Canin", 51.82, 1, 1, [("Azul", "10kg")]),
    (2, "39.png", "Gran Plus Choice", 144.99, 1, 2, [("vermelho", "15kg")]),
    (3, "38.png", "Cibau Medium", 280.34, 1, 2, [("preto", "15kg")]),
    (4, "40.png", "Bravecto MSD", 205.89, 2, 3, [("branco/laranja", "1 comprimido")]),
]
# (nome, categoria, tipo, faixa de preco, variacoes (cor, tamanho))
PRODUTOS_EXTRAS = [
    ("Nutrimax Cães Filhotes", 1, 1, (70, 120), [("", "3kg")]),
    ("Nutrimax Cães Adultos", 1, 2, (110, 190), [("", "10kg")]),
    ("Nutrimax Cães Sênior", 1, 4, (120, 200), [("", "10kg")]),
    ("Nutrimax Gatos Adultos", 1, 2, (60, 110), [("", "3kg")]),
    ("Nutrimax Gatos Filhotes", 1, 1, (40, 80), [("", "1kg")]),          # EM FALTA EM TODAS AS LOJAS
    ("Focinho Feliz Premium Cães", 1, 2, (180, 320), [("", "15kg")]),
    ("Focinho Feliz Premium Gatos", 1, 2, (90, 160), [("", "3kg")]),     # SO NA LOJA MAIS DISTANTE
    ("Pet Vida Light Cães", 1, 2, (100, 170), [("", "10kg")]),
    ("Pet Vida Castrados Gatos", 1, 2, (70, 130), [("", "3kg")]),
    ("Mundo Pet Raças Pequenas", 1, 2, (50, 95), [("", "3kg")]),
    ("Mundo Pet Raças Grandes", 1, 2, (150, 260), [("", "15kg")]),
    ("Natural Pet Grain Free Cães", 1, 2, (160, 280), [("", "7kg")]),
    ("Pulgax Antipulgas Cães P", 2, 3, (55, 95), [("", "1 comprimido")]),
    ("Pulgax Antipulgas Cães M", 2, 3, (65, 110), [("", "1 comprimido")]),
    ("Pulgax Antipulgas Cães G", 2, 3, (80, 130), [("", "1 comprimido")]),
    ("Pulgax Antipulgas Gatos", 2, 3, (55, 95), [("", "1 pipeta")]),
    ("Vermifix Vermífugo", 2, 5, (25, 55), [("", "4 comprimidos")]),
    ("Vermifix Vermífugo Filhotes", 2, 5, (20, 45), [("", "suspensão 20ml")]),
    ("Shampoo Neutro", 3, 6, (18, 35), [("", "500ml")]),
    ("Shampoo Antipulgas", 3, 6, (22, 42), [("", "500ml")]),
    ("Condicionador Pelos Longos", 3, 6, (20, 38), [("", "500ml")]),
    ("Tapete Higiênico", 3, 6, (45, 85), [("", "30 unidades")]),
    ("Areia Sanitária", 3, 6, (20, 40), [("", "4kg")]),
    ("Escova Removedora de Pelos", 3, 6, (15, 30), [("", "")]),
    ("Coleira de Nylon", 4, 7, (20, 45), [("azul", "P"), ("azul", "M"), ("vermelho", "P"), ("vermelho", "M")]),
    ("Guia Retrátil 5m", 4, 7, (35, 70), [("preto", "")]),
    ("Peitoral Conforto", 4, 7, (40, 85), [("preto", "P"), ("preto", "M"), ("preto", "G")]),
    ("Cama Redonda", 4, 7, (70, 150), [("cinza", "P"), ("cinza", "M"), ("cinza", "G")]),
    ("Comedouro de Inox", 4, 7, (18, 40), [("", "P"), ("", "M")]),
    ("Bebedouro Fonte", 4, 7, (90, 160), [("branco", "")]),
    ("Caixa de Transporte", 4, 7, (80, 180), [("azul", "P"), ("azul", "M"), ("azul", "G")]),
    ("Roupinha de Moletom", 4, 7, (30, 65), [("rosa", "P"), ("rosa", "M"), ("verde", "P"), ("verde", "M")]),
    ("Bolinha de Borracha", 5, 8, (8, 20), [("amarelo", "")]),
    ("Osso de Nylon", 5, 8, (15, 35), [("", "P"), ("", "M"), ("", "G")]),
    ("Arranhador Torre", 5, 8, (90, 200), [("bege", "")]),
    ("Varinha com Penas", 5, 8, (10, 25), [("", "")]),
    ("Corda com Nós", 5, 8, (12, 28), [("colorida", "")]),
    ("Pelúcia Sonora", 5, 8, (18, 40), [("marrom", "")]),
]
PRODUTOS_INATIVOS = {"Arranhador Torre", "Pelúcia Sonora", "Bebedouro Fonte"}
EM_FALTA_TOTAL = "Nutrimax Gatos Filhotes"
SO_NA_MAIS_DISTANTE = "Focinho Feliz Premium Gatos"

ESPECIALIDADES = ["Clínica geral", "Clínica geral", "Dermatologia", "Cardiologia", "Ortopedia", "Cirurgia",
                  "Felinos", "Oftalmologia"]
VET_LOJAS = [1, 1, 2, 2, 3, 4, 5, 6]
MANHA, TARDE = ("09:00", "12:00"), ("13:00", "17:00")
JANELAS_VET = [  # {dia ISO (1=seg ... 7=dom): [janelas]}
    {d: [MANHA, TARDE] for d in (1, 2, 3, 4, 5)},
    {d: [MANHA, TARDE] for d in (1, 3, 5)},
    {**{d: [MANHA, TARDE] for d in (2, 4)}, 6: [MANHA]},
    {d: [TARDE] for d in (1, 2, 3, 4, 5)},
    {**{d: [MANHA] for d in (1, 2, 3, 4, 5)}, 6: [MANHA]},
    {d: [MANHA, TARDE] for d in (2, 4, 5)},
    {d: [MANHA, TARDE] for d in (1, 2, 3, 4, 5)},
    {**{d: [MANHA, TARDE] for d in (3, 5)}, 6: [MANHA]},
]
OBSERVACOES = {
    "consulta": ["Check-up de rotina", "Vacinação anual", "Coceira persistente", "Perda de apetite",
                 "Retorno após tratamento", "Vômitos há dois dias", "Avaliação de peso", "Primeira consulta"],
    "exame": ["Exame de sangue", "Ultrassom abdominal", "Eletrocardiograma", "Raio-x", "Exame de vista"],
    "cirurgia": ["Castração", "Retirada de nódulo", "Limpeza de tártaro com anestesia", "Correção ortopédica"],
}
DURACAO_SLOT = timedelta(minutes=30)

# Pedidos: quantidade por status e janela de criacao (em minutos antes de "agora")
PEDIDOS_POR_STATUS = {
    "carrinho": (12, 30, 6 * 1440), "aguardando_pagamento": (10, 30, 2 * 1440), "pago": (12, 60, 2 * 1440),
    "em_separacao": (10, 90, 2 * 1440), "em_entrega": (10, 120, 1440 + 720),
    "entregue": (55, 3 * 1440, 90 * 1440), "cancelado": (11, 1440, 80 * 1440),
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def sem_acento(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def dv(numeros):
    """Digito verificador de CPF."""
    soma = sum(n * p for n, p in zip(numeros, range(len(numeros) + 1, 1, -1)))
    resto = (soma * 10) % 11
    return 0 if resto == 10 else resto


def cpf_ficticio(rng, usados):
    """CPF de 11 digitos com o ultimo digito ERRADO de proposito (invalido)."""
    while True:
        base = [rng.randint(0, 9) for _ in range(9)]
        if len(set(base)) == 1:
            continue
        d1 = dv(base)
        d2 = (dv(base + [d1]) + rng.randint(1, 9)) % 10      # nunca igual ao correto
        cpf = "".join(map(str, base + [d1, d2]))
        if cpf not in usados:
            usados.add(cpf)
            return cpf


def distancia_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def nome_completo(rng, usados):
    while True:
        nome = f"{rng.choice(PRIMEIROS)} {rng.choice(SOBRENOMES)} {rng.choice(SOBRENOMES)}"
        if nome not in usados:
            usados.add(nome)
            return nome


def preco_da_faixa(rng, faixa):
    return round(rng.randint(faixa[0], faixa[1]) - 0.01, 2)      # termina em ,99


def pesos(rng, opcoes):
    """opcoes = [(valor, peso), ...] -> escolhe um valor com probabilidades."""
    return rng.choices([o[0] for o in opcoes], weights=[o[1] for o in opcoes])[0]


# ---------------------------------------------------------------------------
# Geracao dos dados
# ---------------------------------------------------------------------------
def gerar(rng, hoje):
    agora = datetime.combine(hoje, datetime.now().time().replace(microsecond=0))
    D = {t: [] for t in COLUNAS}

    # --- categorias, tipos, banners ---------------------------------------
    D["categoria"] = [(i, n) for i, n in enumerate(CATEGORIAS, 1)]
    D["tipo"] = [(i, n) for i, n in enumerate(TIPOS, 1)]
    D["petshop"] = [(i, img, link, 1) for i, (img, link) in enumerate(BANNERS, 1)]

    # --- lojas -------------------------------------------------------------
    lojas = {}
    for i, (nome, cnpj, endereco, bairro) in enumerate(LOJAS, 1):
        lat, lon = BAIRROS[bairro]
        lojas[i] = (lat, lon)
        D["loja"].append((i, nome, cnpj, endereco, bairro, "Rio de Janeiro", "RJ", lat, lon))
        D["bairro"] = [(i, nome, "Rio de Janeiro", "RJ", lat, lon)
        for i, (nome, (lat, lon)) in enumerate(BAIRROS.items(), 1)]
    loja_mais_distante = max(lojas, key=lambda i: distancia_km(*lojas[i], *BAIRROS["Copacabana"]))

    # --- produtos e estoque ------------------------------------------------
    produtos = {}                      # id -> (nome, preco)
    variacoes = {}                     # id -> lista de (cor, tamanho)
    for pid, img, nome, preco, cat, tipo, vars_ in PRODUTOS_ORIGINAIS:
        produtos[pid] = (nome, preco)
        variacoes[pid] = vars_
        D["produto"].append((pid, img, nome, preco, 1, cat, tipo))
    pid = len(PRODUTOS_ORIGINAIS)
    for nome, cat, tipo, faixa, vars_ in PRODUTOS_EXTRAS:
        pid += 1
        preco = preco_da_faixa(rng, faixa)
        produtos[pid] = (nome, preco)
        variacoes[pid] = vars_
        D["produto"].append((pid, None, nome, preco, 0 if nome in PRODUTOS_INATIVOS else 1, cat, tipo))

    estoque = {l: [] for l in lojas}   # loja -> [(item_id, produto_id, quantidade)]
    item_id = 0
    for l in lojas:
        for p, (nome, _preco) in produtos.items():
            for cor, tamanho in variacoes[p]:
                item_id += 1
                if nome == EM_FALTA_TOTAL:
                    qtd = 0
                elif nome == SO_NA_MAIS_DISTANTE:
                    qtd = 12 if l == loja_mais_distante else 0
                else:
                    sorteio = rng.random()
                    qtd = 0 if sorteio < 0.10 else rng.randint(1, 3) if sorteio < 0.25 else rng.randint(5, 60)
                D["item_estoque"].append((item_id, p, l, cor, tamanho, qtd))
                estoque[l].append((item_id, p, qtd))
    preco_do_item = {r[0]: produtos[r[1]][1] for r in D["item_estoque"]}

    # --- animais (3 originais + 67 gerados) ------------------------------
    D["animal"] = [(1, "cachorro", None, 5, "Max", 32.12), (2, "gato", None, 6, "Rajada", 12.23),
                   (3, "gato", None, 13, "Lula", 13.13)]
    especie_do_animal = {1: "cachorro", 2: "gato", 3: "gato"}
    for aid in range(4, 71):
        especie = pesos(rng, [("cachorro", 58), ("gato", 37), ("coelho", 5)])
        raca, p_min, p_max = rng.choice(RACAS[especie])
        especie_do_animal[aid] = especie
        D["animal"].append((aid, especie, raca, rng.randint(0, IDADE_MAX[especie]), rng.choice(NOMES_PET),
                            round(rng.uniform(p_min, p_max), 2)))

    # --- clientes, enderecos, perfis de pet ------------------------------
    nomes_usados, cpfs_usados = set(), set()
    n_clientes = 45
    pets_do_cliente = {c: [c] for c in range(1, n_clientes + 1)}        # pet c -> cliente c
    for aid in range(n_clientes + 1, 71):                               # pets extras
        pets_do_cliente[rng.randint(1, n_clientes)].append(aid)
    enderecos = {c: [] for c in range(1, n_clientes + 1)}
    end_id = 0
    for c in range(1, n_clientes + 1):
        nome = nome_completo(rng, nomes_usados)
        partes = sem_acento(nome).lower().split()
        email = f"{partes[0]}.{partes[-1]}{c}@example.com"
        cpf = None if rng.random() < 0.05 else cpf_ficticio(rng, cpfs_usados)
        telefone = None if rng.random() < 0.10 else f"(21) 90000-{c:04d}"
        criado = agora - timedelta(days=rng.randint(30, 400), minutes=rng.randint(0, 1439))
        D["cliente"].append((c, nome, cpf, telefone, email, pets_do_cliente[c][0], criado))
        for _ in range(1 if rng.random() < 0.65 else 2):
            end_id += 1
            bairro = rng.choice(list(BAIRROS))
            lat0, lon0 = BAIRROS[bairro]
            rua, numero = rng.choice(RUAS), rng.randint(1, 1800)
            complemento = rng.choice([None, None, "Apto 101", "Apto 302", "Casa 2", "Bloco B"])
            cep = f"2{rng.randint(0, 3)}{rng.randint(100, 999)}-{rng.randint(100, 999)}"
            lat, lon = round(lat0 + rng.uniform(-0.012, 0.012), 6), round(lon0 + rng.uniform(-0.012, 0.012), 6)
            D["endereco"].append((end_id, c, rua, numero, complemento, bairro, cep, "Rio de Janeiro", "RJ", lat, lon))
            texto = f"{rua}, {numero}" + (f" - {complemento}" if complemento else "")
            enderecos[c].append((f"{texto} - {bairro}, Rio de Janeiro/RJ - CEP {cep}", lat, lon))
    perfil_id = 0
    pares = []                                                           # (cliente, animal)
    for c, aids in pets_do_cliente.items():
        for aid in aids:
            perfil_id += 1
            D["perfil_pet"].append((perfil_id, c, aid))
            pares.append((c, aid))

    # --- equipe -------------------------------------------------------------
    crmvs = set()
    vets = []                                                           # (id, especialidade)
    for v, (esp, loja) in enumerate(zip(ESPECIALIDADES, VET_LOJAS), 1):
        while True:
            crmv = f"RJ-{rng.randint(10000, 99999)}"
            if crmv not in crmvs:
                crmvs.add(crmv)
                break
        D["veterinario"].append((v, crmv, nome_completo(rng, nomes_usados), esp, loja))
        vets.append((v, esp))
    hid = 0
    for v, janelas in enumerate(JANELAS_VET, 1):
        for dia, lista in janelas.items():
            for ini, fim in lista:
                hid += 1
                D["horario_atendimento"].append((hid, v, dia, f"{ini}:00", f"{fim}:00"))
    for r in range(1, 7):
        D["recepcionista"].append((r, cpf_ficticio(rng, cpfs_usados), nome_completo(rng, nomes_usados)))
    cnhs = set()
    for e in range(1, 9):
        while True:
            cnh = "".join(str(rng.randint(0, 9)) for _ in range(11))
            if cnh not in cnhs:
                cnhs.add(cnh)
                break
        placa = (f"{rng.choice('ABCDEFGHIJKLMNOPRSTUVWXYZ')}{rng.choice('ABCDEFGHIJKLMNOPRSTUVWXYZ')}"
                 f"{rng.choice('ABCDEFGHIJKLMNOPRSTUVWXYZ')}{rng.randint(0, 9)}"
                 f"{rng.choice('ABCDEFGHIJ')}{rng.randint(0, 9)}{rng.randint(0, 9)}")
        D["entregador"].append((e, cpf_ficticio(rng, cpfs_usados), nome_completo(rng, nomes_usados), cnh, placa))

    # --- agendamentos -------------------------------------------------------
    D["agendamento"] = gerar_agendamentos(rng, agora, hoje, vets, pares, especie_do_animal)

    # --- pedidos, itens, pagamentos ----------------------------------------
    gerar_pedidos(rng, agora, D, lojas, enderecos, estoque, preco_do_item, n_clientes)
    return D


def gerar_agendamentos(rng, agora, hoje, vets, pares, especie_do_animal):
    elegiveis = {
        "consulta": [v for v, _ in vets],
        "exame": [v for v, e in vets if e in ("Clínica geral", "Cardiologia", "Oftalmologia", "Dermatologia")],
        "cirurgia": [v for v, e in vets if e in ("Cirurgia", "Ortopedia")],
    }
    especialidade = dict(vets)
    # todos os horarios possiveis de cada veterinario (de -75 a +30 dias)
    slots = {v: [] for v, _ in vets}
    for v, janelas in enumerate(JANELAS_VET, 1):
        for delta in range(-75, 31):
            dia = hoje + timedelta(days=delta)
            for ini, fim in janelas.get(dia.isoweekday(), []):
                t = datetime.combine(dia, time.fromisoformat(ini))
                limite = datetime.combine(dia, time.fromisoformat(fim))
                while t + DURACAO_SLOT <= limite:
                    slots[v].append(t)
                    t += DURACAO_SLOT
    ocupados = set()                       # (veterinario, horario) ja usados
    animal_ocupado = set()                 # (animal, horario)
    brutos = []

    def escolher_par(vet):
        candidatos = pares
        if especialidade[vet] == "Felinos":
            candidatos = [p for p in pares if especie_do_animal[p[1]] == "gato"]
        return rng.choice(candidatos)

    def status_para(t):
        if t < agora:
            return pesos(rng, [("concluido", 72), ("cancelado", 14), ("nao_compareceu", 14)])
        return pesos(rng, [("agendado", 50), ("confirmado", 42), ("cancelado", 8)])

    tentativas = 0
    while len(brutos) < 105 and tentativas < 5000:
        tentativas += 1
        tipo = pesos(rng, [("consulta", 75), ("exame", 17), ("cirurgia", 8)])
        vet = rng.choice(elegiveis[tipo])
        t = rng.choice(slots[vet])
        if (vet, t) in ocupados:
            continue
        cliente, animal = escolher_par(vet)
        if (animal, t) in animal_ocupado:
            continue
        ocupados.add((vet, t))
        animal_ocupado.add((animal, t))
        brutos.append([cliente, animal, vet, tipo, t, status_para(t)])

    # horarios cancelados no futuro que outro cliente reocupou
    futuros_cancelados = [b for b in brutos if b[5] == "cancelado" and b[4] > agora]
    reocupados = 0
    for b in futuros_cancelados:
        if reocupados >= 5:
            break
        cliente, animal = escolher_par(b[2])
        if (animal, b[4]) in animal_ocupado:
            continue
        animal_ocupado.add((animal, b[4]))
        brutos.append([cliente, animal, b[2], b[3], b[4], "agendado"])
        reocupados += 1

    brutos.sort(key=lambda b: b[4])
    linhas = []
    for i, (cliente, animal, vet, tipo, t, status) in enumerate(brutos, 1):
        recep = rng.randint(1, 6) if status in ("confirmado", "concluido", "nao_compareceu") else None
        obs = rng.choice(OBSERVACOES[tipo]) if rng.random() < 0.7 else None
        criado = min(t - timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 8)), agora - timedelta(minutes=5))
        linhas.append((i, cliente, animal, vet, recep, tipo, t, status, obs, criado))
    return linhas


def gerar_pedidos(rng, agora, D, lojas, enderecos, estoque, preco_do_item, n_clientes):
    brutos = []
    for status, (quantidade, min_min, max_min) in PEDIDOS_POR_STATUS.items():
        for _ in range(quantidade):
            criado = agora - timedelta(minutes=rng.randint(min_min, max_min))
            brutos.append({"status": status, "criado": criado, "cliente": rng.randint(1, n_clientes)})
    brutos.sort(key=lambda b: b["criado"])

    ids_pagamento = set()
    pid = item_linha = pag_id = 0
    for b in brutos:
        pid += 1
        endereco_txt, lat, lon = rng.choice(enderecos[b["cliente"]])
        mais_proxima = min(lojas, key=lambda l: distancia_km(lat, lon, *lojas[l]))
        loja = mais_proxima if rng.random() < 0.7 else rng.choice(list(lojas))
        status, criado = b["status"], b["criado"]

        # itens: sempre da MESMA loja do pedido, de preferencia com estoque
        disponiveis = [e for e in estoque[loja] if e[2] > 0] or estoque[loja]
        qtd_itens = pesos(rng, [(1, 40), (2, 35), (3, 18), (4, 7)])
        escolhidos = rng.sample(disponiveis, min(qtd_itens, len(disponiveis)))
        antigo = (agora - criado) > timedelta(days=20)
        for it_id, _prod, _q in escolhidos:
            item_linha += 1
            preco = preco_do_item[it_id]
            if antigo and rng.random() < 0.25:                    # preco historico menor
                preco = round(preco * rng.uniform(0.85, 0.95), 2)
            D["itens_pedido"].append((item_linha, pid, it_id, pesos(rng, [(1, 70), (2, 22), (3, 8)]), preco))

        # pagamentos
        tentativas = []                                           # (minutos apos criar, aprovado)
        if status == "aguardando_pagamento":
            tentativas = [(rng.randint(2, 30), 0)] * rng.randint(0, 1)
        elif status == "cancelado":
            tentativas = [(rng.randint(2, 20), 0) for _ in range(rng.randint(0, 2))]
        elif status != "carrinho":
            recusadas = pesos(rng, [(0, 70), (1, 20), (2, 10)])
            minuto = 0
            for _ in range(recusadas):
                minuto += rng.randint(2, 12)
                tentativas.append((minuto, 0))
            tentativas.append((minuto + rng.randint(2, 12), 1))
        data_final = None
        for minuto, aprovado in tentativas:
            while True:
                gw = f"MP-{rng.randint(10 ** 11, 10 ** 12 - 1)}"
                if gw not in ids_pagamento:
                    ids_pagamento.add(gw)
                    break
            pag_id += 1
            quando = criado + timedelta(minutes=minuto)
            D["pagamento"].append((pag_id, pid, gw, aprovado, quando))
            if aprovado:
                data_final = quando

        codigo = None if status == "carrinho" else f"PD{criado:%y%m%d}{pid:05d}"
        loja_id = None if status == "carrinho" else loja
        entregador = rng.randint(1, 8) if status in ("em_entrega", "entregue") else None
        D["pedido"].append((pid, b["cliente"], loja_id, entregador, status, codigo, endereco_txt, data_final,
                            criado))


# ---------------------------------------------------------------------------
# Gravacao e verificacao
# ---------------------------------------------------------------------------
def contar(cur):
    total = {}
    for t in ORDEM:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        total[t] = cur.fetchone()[0]
    return total


def gravar(conn, D, reset):
    cur = conn.cursor()
    existentes = contar(cur)
    if sum(existentes.values()) and not reset:
        sys.exit("O banco ja tem dados. Use --reset para apagar tudo e popular de novo.")
    if reset:
        for t in reversed(ORDEM):
            cur.execute(f"DELETE FROM {t}")
        print("Dados antigos apagados.")
    for t in ORDEM:
        colunas = COLUNAS[t]
        sql = f"INSERT INTO {t} ({', '.join(colunas)}) VALUES ({', '.join(['%s'] * len(colunas))})"
        cur.executemany(sql, D[t])
    conn.commit()
    return cur


def verificar(cur):
    print("\nVerificacoes de consistencia (todas devem dar 0):")
    consultas = {
        "itens de pedido de loja diferente da loja do pedido": """
            SELECT COUNT(*) FROM itens_pedido ip
            JOIN pedido p ON p.id = ip.pedido_id JOIN item_estoque ie ON ie.id = ip.item_estoque_id
            WHERE p.loja_id IS NOT NULL AND ie.loja_id <> p.loja_id""",
        "pedidos pagos (ou alem) sem pagamento aprovado": """
            SELECT COUNT(*) FROM pedido p WHERE p.status IN ('pago','em_separacao','em_entrega','entregue')
            AND NOT EXISTS (SELECT 1 FROM pagamento g WHERE g.pedido_id = p.id AND g.aprovado = 1)""",
        "pedidos em carrinho com pagamento": """
            SELECT COUNT(*) FROM pedido p WHERE p.status = 'carrinho'
            AND EXISTS (SELECT 1 FROM pagamento g WHERE g.pedido_id = p.id)""",
        "pedidos sem itens": """
            SELECT COUNT(*) FROM pedido p WHERE NOT EXISTS (SELECT 1 FROM itens_pedido i WHERE i.pedido_id = p.id)""",
        "agendamentos fora da janela de atendimento do veterinario": """
            SELECT COUNT(*) FROM agendamento a WHERE NOT EXISTS (
              SELECT 1 FROM horario_atendimento h WHERE h.veterinario_id = a.veterinario_id
              AND h.dia_semana = WEEKDAY(a.data_hora) + 1
              AND TIME(a.data_hora) >= h.hora_inicio AND ADDTIME(TIME(a.data_hora), '00:30:00') <= h.hora_fim)""",
    }
    for descricao, sql in consultas.items():
        cur.execute(sql)
        print(f"  {descricao}: {cur.fetchone()[0]}")


def main():
    ap = argparse.ArgumentParser(description="Popula o banco do agente com dados ficticios.")
    ap.add_argument("--reset", action="store_true", help="apaga todos os dados antes de popular")
    ap.add_argument("--hoje", help="data de referencia AAAA-MM-DD (padrao: hoje)")
    args = ap.parse_args()

    if "agente" not in Config.DB_NAME:
        sys.exit(f"Por seguranca, este script so roda em banco com 'agente' no nome (DB_NAME={Config.DB_NAME}).")
    hoje = date.fromisoformat(args.hoje) if args.hoje else date.today()

    D = gerar(random.Random(2026), hoje)
    conn = mysql.connector.connect(host=Config.DB_HOST, port=Config.DB_PORT, database=Config.DB_NAME,
                                   user=Config.DB_USER, password=Config.DB_PASSWORD, charset="utf8mb4",
                                   connection_timeout=10)
    try:
        cur = gravar(conn, D, args.reset)
    except mysql.connector.Error as erro:
        conn.rollback()
        conn.close()
        sys.exit(f"Erro do banco; nada foi gravado.\n{erro}")

    total = 0
    print(f"\nBanco: {Config.DB_NAME} | data de referencia: {hoje}\n")
    print(f"{'tabela':<22}{'linhas':>8}")
    for t in ORDEM:
        print(f"{t:<22}{len(D[t]):>8}")
        total += len(D[t])
    print(f"{'TOTAL':<22}{total:>8}")
    verificar(cur)
    conn.close()


if __name__ == "__main__":
    main()