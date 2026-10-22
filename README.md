# Pet Delivery — Agente com ferramentas

## Descrição

O **Pet Delivery** é um projeto em Python que reúne uma aplicação web em Flask, um banco de dados relacional MySQL e um conjunto de ferramentas de negócio para consultar informações de um pet shop. O projeto está estruturado para que um agente de IA possa, futuramente, interpretar pedidos em linguagem natural e solicitar a execução dessas ferramentas de forma controlada.

A arquitetura separa responsabilidades: a interface recebe a mensagem, a aplicação web trata a requisição, a camada de ferramentas valida os argumentos e executa a regra de negócio, e o MySQL fornece os dados persistidos. O modelo de linguagem não deve montar nem executar SQL diretamente: ele deve solicitar uma ferramenta pelo nome e fornecer apenas os argumentos previstos no contrato dela.

**Estado atual importante:** a estrutura de ferramentas e o executor estão implementados, mas a rota web `/api/chat` ainda devolve uma resposta de eco (`[eco] Você disse: ...`). A integração com um provedor de LLM e o ciclo completo de seleção/execução de ferramentas não estão conectados à conversa do navegador nesta versão. Portanto, o chat visual ainda não é um agente de IA funcional de ponta a ponta.

## Funcionalidades

### Aplicação web
- Página de chat servida pelo Flask.
- Envio de mensagens do navegador para a API `/api/chat` usando JSON.
- Validação de mensagem vazia e limite de 1.000 caracteres.
- Rota `/health` para verificar se o servidor está ativo.
- Rota `/health/db` para testar a conectividade com o MySQL.
- Interface com estilos próprios, mensagens de usuário/assistente e alternância de tema claro/escuro.

### Ferramentas de negócio
- Busca de produtos ativos por palavras relacionadas ao nome, categoria, tipo, cor ou tamanho.
- Consulta de estoque por produto, loja e variação.
- Listagem de lojas e pesquisa de lojas próximas de um bairro.
- Comparação de disponibilidade de um produto entre lojas próximas.
- Consulta de perfil, animais e endereços do cliente identificado no contexto.
- Consulta de agendamentos do cliente.
- Listagem de veterinários, especialidades e horários de atendimento.
- Consulta de horários disponíveis para atendimento veterinário.
- Listagem de pedidos do cliente e consulta dos detalhes de um pedido, incluindo itens e resumo de pagamento.
- Respostas padronizadas para erros de argumentos, dados inexistentes, falhas de banco e erros internos.

### Testes e dados de demonstração
- Testes automatizados com `pytest` para regras das ferramentas, validação de argumentos, tratamento de falhas e cálculo de distância.
- Script para popular o banco com dados fictícios e determinísticos.
- Script de linha de comando para executar uma ferramenta isoladamente, sem interface web nem modelo de IA.

## Estrutura do Projeto

```text
petdelivery-agente/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── db.py
│   ├── routes.py
│   ├── static/
│   │   └── logo.png
│   ├── templates/
│   │   └── chat.html
│   └── tools/
│       ├── __init__.py
│       ├── base.py
│       ├── agenda.py
│       ├── catalogo.py
│       ├── cliente.py
│       ├── geo.py
│       ├── lojas.py
│       └── pedidos.py
├── scripts/
│   ├── popular_dados.py
│   └── testar_ferramenta.py
├── sql/
│   ├── 01_criar_banco.sql
│   ├── 02_criar_tabelas.sql
│   └── 03_bairro.sql
├── tests/
│   ├── conftest.py
│   ├── test_agenda.py
│   ├── test_catalogo.py
│   ├── test_executor.py
│   ├── test_geo.py
│   └── test_lojas.py
├── .env.example
├── .gitignore
├── petdelivery_backup.sql
├── pytest.ini
├── requirements.txt
└── run.py
```

### `app/` — aplicação principal

- **`__init__.py`**: implementa a fábrica `create_app()`. Cria a instância Flask, carrega as configurações e registra o blueprint das rotas. Centralizar a criação do app facilita iniciar a aplicação e reutilizá-la nos testes.
- **`config.py`**: lê configurações do ambiente, incluindo parâmetros de conexão do MySQL, limite de mensagem e modo de depuração. Usa `python-dotenv` para carregar valores de um arquivo `.env` durante o desenvolvimento.
- **`db.py`**: concentra a criação de conexões com MySQL. As ferramentas recebem a conexão por meio de um `Contexto`; quem abre a conexão é responsável por fechá-la.
- **`routes.py`**: define os endpoints HTTP. `/` renderiza a interface, `/health` verifica o servidor, `/health/db` executa uma consulta simples ao banco e `/api/chat` valida a mensagem e, atualmente, devolve o eco de teste.
- **`static/`**: arquivos estáticos da interface, como a imagem de logotipo.
- **`templates/chat.html`**: HTML, CSS e JavaScript da página de chat. Envia a mensagem para `/api/chat` e exibe a resposta retornada pelo servidor. A aparência da interface não significa que a integração com IA já esteja conectada.

### `app/tools/` — ferramentas do agente

Este diretório contém funções Python que representam ações delimitadas do sistema. Cada ferramenta declara um nome, uma descrição e seus parâmetros por meio do decorador `@ferramenta`. Isso permite registrar as funções e gerar especificações estruturadas que podem ser convertidas para o formato de *tool/function calling* de um provedor de IA.

- **`base.py` — infraestrutura comum das ferramentas**
  - `Contexto`: transporta recursos controlados pela aplicação, como a conexão com o banco e, quando disponível, o identificador do cliente autenticado.
  - `Ferramenta`: estrutura que guarda nome, descrição, esquema de parâmetros e função executável.
  - `REGISTRO`: dicionário central que associa o nome público de cada ferramenta à sua definição.
  - `@ferramenta`: decorador que registra a função e impede nomes duplicados.
  - `especificacoes()`: transforma os metadados registrados em uma estrutura semelhante a JSON Schema, com tipos, descrições, parâmetros obrigatórios e `additionalProperties: false`. Essa lista é a base para apresentar as ferramentas a um modelo de linguagem.
  - `executar()`: ponto único de entrada para execução. Confere se a ferramenta existe, se os argumentos são um objeto, se não foram enviados parâmetros extras e se os obrigatórios estão presentes. Em seguida chama a função e devolve um resultado padronizado.
  - Validadores auxiliares: `exigir_inteiro`, `exigir_texto`, `escapar_like`, `dinheiro` e `exigir_cliente` tratam entradas e regras recorrentes.
  - `ErroFerramenta`: representa erros esperados de negócio ou validação com código e mensagem próprios.
  - Tratamento de exceções: erros conhecidos, falhas do MySQL e erros inesperados são convertidos em respostas controladas. Detalhes técnicos são registrados no log, evitando que mensagens internas sejam devolvidas ao chamador.

  O contrato de retorno de `executar()` é sempre um dos seguintes formatos conceituais:

  ```python
  {"ok": True, "dados": ...}
  {"ok": False, "erro": {"codigo": "...", "mensagem": "..."}}
  ```

- **`catalogo.py` — catálogo e estoque**
  - `buscar_produtos`: pesquisa produtos ativos usando palavras no nome, categoria, tipo ou variações como cor e tamanho. Limita a busca a seis palavras e retorna até dez resultados. Deve ser usada para descobrir o `produto_id` antes de consultar estoque.
  - `consultar_estoque`: consulta a quantidade de um produto, podendo filtrar por loja e variação. Estoque igual a zero representa falta do produto, não necessariamente erro de consulta.
  - As consultas utilizam parâmetros SQL, em vez de concatenar diretamente os valores fornecidos pelo usuário na instrução SQL.

- **`lojas.py` — lojas e proximidade**
  - `listar_lojas`: lista lojas, com possibilidade de filtrar por bairro.
  - `lojas_proximas`: ordena lojas por distância em linha reta a partir de um bairro. Se receber um `produto_id`, também compara estoque e informa a loja mais próxima que possui o item, inclusive quando ela não aparece entre as lojas exibidas no conjunto principal de resultados.
  - O módulo depende de coordenadas geográficas dos bairros e lojas e das funções de cálculo do módulo `geo.py`.

- **`geo.py` — cálculo geográfico**
  - `distancia_km`: calcula a distância aproximada em linha reta entre duas coordenadas de latitude/longitude usando a fórmula de Haversine e um raio médio terrestre de 6.371 km.
  - A distância calculada não representa tempo de viagem nem rota por ruas. Para isso seria necessária uma API ou serviço de roteamento externo.

- **`cliente.py` — informações do cliente**
  - `consultar_meu_perfil`: consulta os dados de perfil do cliente do contexto.
  - `listar_meus_pets`: lista os animais associados ao cliente.
  - `listar_meus_enderecos`: lista os endereços cadastrados para o cliente.
  - `listar_meus_agendamentos`: consulta os agendamentos do cliente e permite selecionar o período, como futuros, passados ou todos.
  - As ferramentas pessoais usam `Contexto.cliente_id` por meio de `exigir_cliente()`. O identificador do cliente não deve ser escolhido pelo modelo como argumento: em uma aplicação completa, ele deve vir da sessão autenticada pela aplicação.

- **`agenda.py` — veterinários e disponibilidade**
  - `listar_veterinarios`: lista veterinários, suas especialidades, a loja em que atendem e as janelas de atendimento; permite filtrar por especialidade ou loja.
  - `consultar_horarios_disponiveis`: consulta horários livres de atendimento em intervalos de 30 minutos, considerando o dia da semana, os agendamentos existentes e limites de data. A implementação limita a consulta a até 60 dias à frente e, para o dia atual, exige pelo menos uma hora de antecedência.
  - O módulo valida datas no formato `AAAA-MM-DD` e utiliza status de agendamento definidos pela regra de negócio para determinar ocupação.

- **`pedidos.py` — pedidos e pagamentos**
  - `listar_meus_pedidos`: lista pedidos recentes do cliente do contexto e pode filtrar pela situação do pedido.
  - `consultar_pedido`: consulta um pedido específico pertencente ao cliente, incluindo itens, total, situação, loja, endereço de entrega, informações do entregador quando aplicável e um resumo do pagamento.
  - Para detalhes de um pedido, o identificador deve ser obtido pela listagem do próprio cliente; o escopo do cliente deve continuar sendo validado pela aplicação.

- **`tools/__init__.py`**: importa os módulos de ferramentas para que os decoradores sejam executados e as ferramentas sejam registradas em `REGISTRO`. Também expõe as funções comuns (`executar`, `especificacoes`, `Contexto` etc.) para os demais módulos.

### `sql/` — estrutura do banco de dados

- **`01_criar_banco.sql`**: cria o banco `petdelivery_agente`, configura charset/collation e define um usuário MySQL com permissões limitadas ao banco do projeto. Revise o script e substitua qualquer credencial de exemplo por uma senha própria antes de executá-lo.
- **`02_criar_tabelas.sql`**: define as tabelas relacionais centrais, incluindo categorias e tipos, lojas, produtos, itens de estoque, animais, clientes, endereços, perfis de pets, veterinários, horários de atendimento, recepcionistas, entregadores, agendamentos, pedidos, itens de pedido, pagamentos e registros de pet shops.
- **`03_bairro.sql`**: cria a tabela de bairros, que armazena cidade, estado e coordenadas geográficas usadas como referência para calcular proximidade de lojas.
- **`petdelivery_backup.sql`**: arquivo de backup presente na raiz do projeto. Verifique sua origem e conteúdo antes de restaurá-lo; não presuma que seja equivalente aos scripts atuais.

As chaves primárias e estrangeiras estabelecem as relações entre clientes, animais, lojas, estoque, agendamentos e pedidos. A ordem de criação e a ordem de inserção importam por causa dessas dependências.

### `scripts/` — apoio ao desenvolvimento

- **`popular_dados.py`**: popula o banco com dados fictícios determinísticos para desenvolvimento e testes. Pode preencher apenas um banco vazio ou, com `--reset`, recriar os dados conforme a lógica do script. O reset pode apagar dados existentes; use somente em ambiente de desenvolvimento e confirme o banco configurado antes de executá-lo.
- **`testar_ferramenta.py`**: executa uma ferramenta diretamente pelo terminal, sem precisar de um modelo de IA. `--lista` exibe as especificações registradas. Também aceita nome de ferramenta, argumentos no formato `chave=valor` e `--cliente=ID` para simular o cliente colocado no contexto durante o teste. Essa opção é apenas uma simulação local, não um mecanismo de autenticação para produção.

### `tests/` — testes automatizados

- **`conftest.py`**: define fixtures compartilhadas, cria o contexto e abre/fecha a conexão usada pelos testes. Os testes esperam que o banco esteja populado com os dados de demonstração.
- **`test_agenda.py`**: testa as regras de listagem de veterinários e consulta de disponibilidade, incluindo validações de data e horários.
- **`test_catalogo.py`**: verifica busca de produtos, consulta de estoque, categorias/tipos e entradas inválidas.
- **`test_executor.py`**: testa o registro e executor de ferramentas, rejeição de parâmetros inventados, ausência de obrigatórios e conversão de falhas em erros controlados.
- **`test_geo.py`**: verifica propriedades do cálculo de distância, como distância zero entre pontos iguais e simetria.
- **`test_lojas.py`**: testa filtros por bairro, ordenação por distância, estoque e casos de produto disponível ou indisponível.
- **`pytest.ini`**: configura os diretórios de importação e localização dos testes.

### Arquivos de configuração e inicialização

- **`run.py`**: ponto de entrada para iniciar o servidor Flask local.
- **`requirements.txt`**: lista as dependências Python necessárias para a aplicação e os testes.
- **`.env.example`**: modelo das variáveis de ambiente. Deve ser copiado para `.env` e preenchido localmente.
- **`.gitignore`**: define arquivos e diretórios que não devem ser versionados.
- **`.venv/`**: ambiente virtual Python local, quando existente. Não deve ser enviado ao repositório; cada desenvolvedor deve criar seu próprio ambiente.
- **`.pytest_cache/` e `__pycache__/`**: arquivos temporários gerados por ferramentas de execução; não são parte do código-fonte necessário para a aplicação.

## Ferramentas e tecnologias

| Tecnologia | Papel no projeto |
|---|---|
| **Python** | Linguagem da aplicação, regras de negócio, ferramentas, scripts e testes. |
| **Flask** | Framework web responsável pela aplicação HTTP, rotas e renderização do template de chat. |
| **MySQL** | Banco relacional que armazena catálogo, estoque, clientes, pets, lojas, agendamentos, pedidos e pagamentos. |
| **mysql-connector-python** | Driver que permite à aplicação Python abrir conexões e executar consultas parametrizadas no MySQL. |
| **python-dotenv** | Carrega variáveis de configuração definidas no arquivo `.env` durante o desenvolvimento. |
| **pytest** | Framework de testes automatizados, com fixtures compartilhadas e verificação das regras esperadas. |
| **HTML, CSS e JavaScript** | Implementam a interface do chat no navegador e a comunicação com a API Flask. |
| **JSON / JSON Schema simplificado** | Formato de troca de mensagens e descrição dos parâmetros que podem ser apresentados a um modelo de IA para chamada de ferramentas. |
| **Fórmula de Haversine** | Estima a distância geográfica em linha reta entre coordenadas de bairros e lojas. |

### Como funciona o registro e a execução de ferramentas

1. O módulo de uma ferramenta é importado por `app/tools/__init__.py`.
2. O decorador `@ferramenta` registra seu nome, descrição, parâmetros e função em `REGISTRO`.
3. `especificacoes()` expõe as descrições e os parâmetros, incluindo quais são obrigatórios, para que um orquestrador possa apresentá-los a um LLM.
4. Em uma integração completa, o LLM interpreta a mensagem e solicita uma ferramenta com argumentos estruturados. A aplicação recebe essa solicitação, mas não deve confiar cegamente nela.
5. `executar()` valida nome, tipo geral dos argumentos, parâmetros permitidos e campos obrigatórios antes de chamar a função Python.
6. A função aplica validações de domínio, consulta o banco por meio de SQL parametrizado e devolve os dados.
7. O executor converte o resultado ou a falha em um formato previsível para o orquestrador.
8. Em um ciclo completo de tool calling, o resultado da ferramenta seria enviado de volta ao LLM para compor uma resposta em linguagem natural. **Esse ciclo ainda precisa ser integrado à rota `/api/chat`.**

Esse desenho reduz o acoplamento entre o provedor de IA e as regras de negócio: o provedor pode mudar sem que toda a lógica de consulta ao banco precise ser reescrita, desde que um adaptador traduza as especificações e chamadas para o formato esperado pela API escolhida.

## Execução

### 1. Pré-requisitos

- Python instalado (o projeto foi desenvolvido/testado com Python 3.13 no ambiente atual; confira a compatibilidade das dependências no seu sistema).
- MySQL Server em execução.
- Acesso ao terminal na pasta raiz `petdelivery-agente`.

### 2. Criar e ativar o ambiente virtual

No Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

No Prompt de Comando (CMD), a ativação é:

```bat
.venv\Scripts\activate.bat
```

### 3. Configurar as variáveis de ambiente

Copie o arquivo de exemplo:

```powershell
Copy-Item .env.example .env
```

Edite o `.env` e configure os valores do seu MySQL, por exemplo:

```dotenv
FLASK_DEBUG=1
DB_HOST=localhost
DB_PORT=3306
DB_NAME=petdelivery_agente
DB_USER=petdelivery_app
DB_PASSWORD=sua_senha_local
```

O valor de `DB_NAME` precisa corresponder ao banco que será usado. O código de configuração contém um valor padrão diferente (`petdelivery`), então é recomendável definir explicitamente `petdelivery_agente` no `.env` se esse for o banco criado pelos scripts SQL.

Não versione o `.env`, senhas, chaves de API ou dumps com dados sensíveis. Use credenciais próprias e com privilégios mínimos.

### 4. Criar a estrutura do banco

Com o MySQL configurado, execute os scripts SQL na ordem indicada, revisando antes as credenciais e os comandos de criação de usuário:

1. `sql/01_criar_banco.sql`
2. `sql/02_criar_tabelas.sql`
3. `sql/03_bairro.sql`

Execute-os com uma ferramenta MySQL, como MySQL Workbench ou cliente de linha de comando. Se o banco já existir, confira o estado atual antes de executar novamente os scripts. O usuário da aplicação precisa ter as permissões necessárias para as operações que as ferramentas executam.

### 5. Popular o banco com dados fictícios

Na raiz do projeto:

```powershell
python scripts/popular_dados.py
```

Para recriar os dados de demonstração:

```powershell
python scripts/popular_dados.py --reset
```

**Atenção:** `--reset` é uma operação destrutiva para os dados que o script substitui. Nunca execute contra um banco de produção ou que contenha dados que precisem ser preservados.

O gerador inclui cenários de teste úteis, como produtos sem estoque em nenhuma loja, produto disponível apenas em uma loja distante, estoque baixo, horários cancelados e pedidos em diferentes situações.

### 6. Iniciar a aplicação web

```powershell
python run.py
```

Abra no navegador o endereço local informado pelo Flask (normalmente `http://127.0.0.1:5000`). Para conferir o estado do servidor, acesse `/health`; para testar a conectividade com o banco, acesse `/health/db`.

Lembre-se: nesta versão, o endpoint de chat responde com eco. Para que a conversa use as ferramentas, ainda é necessário implementar e configurar a integração com o provedor de LLM e seu ciclo de chamadas de ferramentas.

### 7. Executar uma ferramenta sem IA

Listar as especificações disponíveis:

```powershell
python scripts/testar_ferramenta.py --lista
```

Pesquisar produtos:

```powershell
python scripts/testar_ferramenta.py buscar_produtos termo="racao gatos"
```

Consultar estoque usando o ID retornado pela busca:

```powershell
python scripts/testar_ferramenta.py consultar_estoque produto_id=9
```

Listar lojas de um bairro:

```powershell
python scripts/testar_ferramenta.py listar_lojas bairro=Tijuca
```

Consultar dados pessoais com um cliente de teste no contexto:

```powershell
python scripts/testar_ferramenta.py listar_meus_pets --cliente=1
```

Os IDs e os resultados dependem dos dados presentes no banco. O comando `--cliente` serve para teste local e não substitui autenticação real.

### 8. Executar os testes

Com o ambiente virtual ativo, banco criado e dados de teste carregados:

```powershell
pytest
```

Para executar um arquivo específico:

```powershell
pytest tests/test_executor.py -v
```

Os testes se conectam ao banco configurado e pressupõem dados de demonstração. Leia o teste e confira o banco-alvo antes de executar, principalmente se estiver usando um ambiente compartilhado.

## Saída Esperada

- O servidor Flask inicia e disponibiliza a página de chat.
- `/health` retorna um JSON indicando `status: ok` quando a aplicação está em execução.
- `/health/db` retorna `status: ok` quando a aplicação consegue consultar o MySQL; se o banco estiver indisponível, retorna erro HTTP 503 com uma mensagem genérica.
- `scripts/testar_ferramenta.py --lista` imprime as especificações das ferramentas em JSON.
- A execução isolada de uma ferramenta retorna JSON com `ok: true` e `dados`, ou `ok: false` e um objeto `erro` com código e mensagem.
- `pytest` apresenta o relatório dos testes aprovados ou as falhas encontradas.
- O chat web, na versão atual, exibe uma resposta de eco e não uma resposta produzida por um LLM.

## Manutenção

- **Adicionar ferramenta:** crie ou escolha um módulo em `app/tools/`, defina a função com `@ferramenta`, descreva os parâmetros e importe o módulo em `app/tools/__init__.py` para que o registro aconteça.
- **Validar entradas:** trate todos os argumentos recebidos de um LLM como não confiáveis. Declare apenas os parâmetros necessários, rejeite campos extras, valide tipos e limites e use SQL parametrizado.
- **Manter privacidade:** ferramentas que consultam dados pessoais devem derivar a identidade do cliente de uma sessão autenticada controlada pela aplicação, não de um `cliente_id` escolhido pelo modelo.
- **Tratar erros:** use `ErroFerramenta` para falhas esperadas e evite devolver SQL, credenciais, stack traces ou detalhes internos ao usuário.
- **Alterar o banco:** atualize os scripts SQL e o gerador de dados fictícios, além das ferramentas e dos testes afetados. Respeite chaves estrangeiras e a ordem de inserção.
- **Manter dados de teste:** se uma ferramenta depender de um novo cenário, inclua esse cenário no gerador determinístico e escreva testes para o comportamento esperado.
- **Configurar integrações:** mantenha chaves de APIs em variáveis de ambiente e crie uma camada adaptadora para traduzir as especificações de `especificacoes()` para o formato do provedor de IA escolhido.
- **Não versionar artefatos locais:** evite enviar `.env`, `.venv`, caches, credenciais, dados reais ou backups não revisados ao repositório.

## Observações Gerais

- O projeto contém a base para um agente que usa ferramentas, mas a integração entre o chat, um LLM e a execução automática das ferramentas ainda não está finalizada.
- Não há, na implementação analisada, uma integração efetiva com API externa de IA. O campo comentado `LLM_API_KEY` no `.env.example` é apenas uma indicação de configuração futura.
- A distância de `lojas_proximas` é geográfica em linha reta; não deve ser apresentada como distância por ruas ou estimativa de entrega.
- Os dados produzidos por `popular_dados.py` são fictícios e destinados a desenvolvimento/testes.
- O esquema das ferramentas restringe os argumentos declarados, mas isso não substitui autenticação, autorização, controle de acesso, limites de uso e validação no servidor.
- O banco configurado na aplicação deve ser o mesmo que recebeu os scripts e os dados de demonstração. Confirme especialmente `DB_NAME` antes de rodar os scripts e os testes.
- Antes de publicar ou compartilhar o projeto, revise o arquivo `.env`, os scripts SQL e os backups para garantir que não contenham credenciais reais. Caso alguma senha tenha sido compartilhada em um arquivo ou repositório, troque-a.

## Responsável

Projeto acadêmico de Engenharia da Computação — **Pet Delivery: estrutura de agente com ferramentas para consulta a dados relacionais**.

Responsável: **Vinicius Mello**.
