-- =====================================================================
-- Passo 2.3: tabelas do banco do agente (petdelivery_agente)
--
-- LEGENDA DAS ALTERACOES em relacao ao e-commerce (db.sqlite3):
--   [IGUAL]     existia e foi mantido
--   [AJUSTE]    existia, mas mudou (tipo, obrigatoriedade, unicidade, nome)
--   [NOVO]      nao existia; o agente precisa
--   [REMOVIDO]  existia e nao foi migrado
--
-- Todas as 16 tabelas do e-commerce estao aqui,
-- mais 2 tabelas novas: horario_atendimento e entregador.
-- =====================================================================

USE petdelivery_agente;
SET NAMES utf8mb4;

-- ---------------------------------------------------------------------
-- 1) Catalogo: categoria e tipo
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categoria (          -- [IGUAL] (era lojas_categoria)
  id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nome  VARCHAR(100) NOT NULL,                  -- [AJUSTE] era opcional; agora obrigatorio e unico
  PRIMARY KEY (id),
  UNIQUE KEY uq_categoria_nome (nome)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS tipo (               -- [IGUAL] (era lojas_tipo)
  id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nome  VARCHAR(100) NOT NULL,                  -- [AJUSTE] obrigatorio e unico
  PRIMARY KEY (id),
  UNIQUE KEY uq_tipo_nome (nome)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2) Loja
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loja (               -- [IGUAL] (era lojas_loja)
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nome_fantasia  VARCHAR(200) NOT NULL,         -- [IGUAL]
  cnpj           VARCHAR(18)  NOT NULL,         -- [AJUSTE] coluna era "CNPJ"; agora minuscula e unica
  endereco       VARCHAR(200) NOT NULL,         -- [IGUAL] (rua e numero em texto)
  bairro         VARCHAR(100) NULL,             -- [NOVO]
  cidade         VARCHAR(100) NULL,             -- [NOVO]
  estado         CHAR(2)      NULL,             -- [NOVO]
  latitude       DECIMAL(9,6) NULL,             -- [NOVO] permite achar a "loja mais proxima"
  longitude      DECIMAL(9,6) NULL,             -- [NOVO]
  PRIMARY KEY (id),
  UNIQUE KEY uq_loja_cnpj (cnpj)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3) Produto e estoque
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS produto (            -- [IGUAL] (era lojas_produto)
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  imagem        VARCHAR(100)  NULL,             -- [IGUAL] nome do arquivo da imagem
  nome          VARCHAR(200)  NOT NULL,         -- [AJUSTE] era opcional
  preco         DECIMAL(10,2) NOT NULL,         -- [AJUSTE] no SQLite nao tinha precisao; agora 2 casas
  ativo         BOOLEAN       NOT NULL DEFAULT 1,  -- [IGUAL]
  categoria_id  INT UNSIGNED  NOT NULL,         -- [AJUSTE] era opcional
  tipo_id       INT UNSIGNED  NOT NULL,         -- [AJUSTE] era opcional
  PRIMARY KEY (id),
  CONSTRAINT ck_produto_preco CHECK (preco >= 0),
  CONSTRAINT fk_produto_categoria FOREIGN KEY (categoria_id) REFERENCES categoria (id),
  CONSTRAINT fk_produto_tipo      FOREIGN KEY (tipo_id)      REFERENCES tipo (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS item_estoque (       -- [AJUSTE] (era lojas_itemestoque)
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  produto_id  INT UNSIGNED NOT NULL,            -- [AJUSTE] era opcional
  loja_id     INT UNSIGNED NOT NULL,            -- [NOVO] estoque POR LOJA (antes era global)
  cor         VARCHAR(100) NOT NULL DEFAULT '', -- [AJUSTE] vazio = sem variacao (permite chave unica)
  tamanho     VARCHAR(100) NOT NULL DEFAULT '', -- [AJUSTE] idem
  quantidade  INT UNSIGNED NOT NULL DEFAULT 0,  -- [IGUAL] nunca negativo
  PRIMARY KEY (id),
  UNIQUE KEY uq_estoque_variacao (produto_id, loja_id, cor, tamanho),  -- [NOVO]
  CONSTRAINT fk_estoque_produto FOREIGN KEY (produto_id) REFERENCES produto (id),
  CONSTRAINT fk_estoque_loja    FOREIGN KEY (loja_id)    REFERENCES loja (id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4) Animais e clientes
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS animal (             -- [IGUAL] (era lojas_animal)
  id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
  especie  VARCHAR(50)  NOT NULL,               -- [AJUSTE] era opcional
  raca     VARCHAR(100) NULL,                   -- [NOVO] vem do modelo academico
  idade    SMALLINT UNSIGNED NULL,              -- [IGUAL] em anos
  nome     VARCHAR(100) NOT NULL,               -- [AJUSTE] era opcional
  peso     DECIMAL(5,2) NULL,                   -- [AJUSTE] em kg; agora com precisao
  PRIMARY KEY (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS cliente (            -- [AJUSTE] (era lojas_cliente)
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nome       VARCHAR(200) NOT NULL,             -- [AJUSTE] era opcional
  cpf        CHAR(11)     NULL,                 -- [AJUSTE] so digitos e unico (no SQLite havia CPF repetido)
  telefone   VARCHAR(15)  NULL,                 -- [IGUAL]
  email      VARCHAR(200) NOT NULL,             -- [AJUSTE] obrigatorio e unico (identifica o cliente)
  animal_id  INT UNSIGNED NULL,                 -- [IGUAL] "pet principal"; a posse de verdade fica em perfil_pet
  -- usuario_id (liga ao auth_user do Django)   -- [REMOVIDO] o login fica para o passo de seguranca
  criado_em  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- [NOVO]
  PRIMARY KEY (id),
  UNIQUE KEY uq_cliente_cpf (cpf),
  UNIQUE KEY uq_cliente_email (email),
  CONSTRAINT ck_cliente_cpf CHECK (cpf IS NULL OR cpf REGEXP '^[0-9]{11}$'),
  CONSTRAINT fk_cliente_animal FOREIGN KEY (animal_id) REFERENCES animal (id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS endereco (           -- [AJUSTE] (era lojas_endereco)
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  cliente_id   INT UNSIGNED NOT NULL,           -- [AJUSTE] era opcional (no SQLite havia endereco sem dono)
  rua          VARCHAR(255) NOT NULL,           -- [AJUSTE] obrigatorio
  numero       INT UNSIGNED NOT NULL,           -- [IGUAL]
  complemento  VARCHAR(100) NULL,               -- [IGUAL]
  bairro       VARCHAR(100) NULL,               -- [NOVO]
  cep          VARCHAR(9)   NULL,               -- [IGUAL]
  cidade       VARCHAR(100) NOT NULL,           -- [AJUSTE] obrigatorio
  estado       VARCHAR(50)  NOT NULL,           -- [AJUSTE] obrigatorio
  latitude     DECIMAL(9,6) NULL,               -- [NOVO] opcional; para distancia ate a loja
  longitude    DECIMAL(9,6) NULL,               -- [NOVO]
  PRIMARY KEY (id),
  CONSTRAINT fk_endereco_cliente FOREIGN KEY (cliente_id) REFERENCES cliente (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS perfil_pet (         -- [AJUSTE] (era lojas_perfilpet) fonte da verdade: quem e dono de qual animal
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  cliente_id  INT UNSIGNED NOT NULL,            -- [AJUSTE] era opcional
  animal_id   INT UNSIGNED NOT NULL,            -- [AJUSTE] era opcional
  PRIMARY KEY (id),
  UNIQUE KEY uq_perfil_cliente_animal (cliente_id, animal_id),  -- [NOVO] sem duplicar o par
  CONSTRAINT fk_perfil_cliente FOREIGN KEY (cliente_id) REFERENCES cliente (id),
  CONSTRAINT fk_perfil_animal  FOREIGN KEY (animal_id)  REFERENCES animal (id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 5) Equipe: veterinario, horario de atendimento, recepcionista, entregador
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS veterinario (        -- [AJUSTE] (era lojas_veterinario)
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  crmv           VARCHAR(20)  NOT NULL,         -- [AJUSTE] coluna era "CRMV"; agora minuscula e unica
  nome           VARCHAR(200) NOT NULL,         -- [IGUAL]
  especialidade  VARCHAR(100) NOT NULL,         -- [IGUAL]
  loja_id        INT UNSIGNED NULL,             -- [NOVO] onde o veterinario atende
  PRIMARY KEY (id),
  UNIQUE KEY uq_veterinario_crmv (crmv),
  CONSTRAINT fk_veterinario_loja FOREIGN KEY (loja_id) REFERENCES loja (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS horario_atendimento (  -- [NOVO] janelas de trabalho; base de "horarios disponiveis"
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  veterinario_id  INT UNSIGNED NOT NULL,
  dia_semana      TINYINT UNSIGNED NOT NULL,    -- 1 = segunda ... 7 = domingo
  hora_inicio     TIME NOT NULL,
  hora_fim        TIME NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT ck_horario_dia   CHECK (dia_semana BETWEEN 1 AND 7),
  CONSTRAINT ck_horario_faixa CHECK (hora_fim > hora_inicio),
  CONSTRAINT fk_horario_veterinario FOREIGN KEY (veterinario_id) REFERENCES veterinario (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS recepcionista (      -- [AJUSTE] (era lojas_recepcionista)
  id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  cpf   CHAR(11)     NOT NULL,                  -- [AJUSTE] so digitos e unico
  nome  VARCHAR(200) NOT NULL,                  -- [IGUAL]
  PRIMARY KEY (id),
  UNIQUE KEY uq_recepcionista_cpf (cpf),
  CONSTRAINT ck_recepcionista_cpf CHECK (cpf REGEXP '^[0-9]{11}$')
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS entregador (         -- [NOVO] vem do modelo academico; o pedido precisa de entregador
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  cpf            CHAR(11)     NOT NULL,
  nome           VARCHAR(200) NOT NULL,
  cnh            VARCHAR(11)  NOT NULL,
  placa_veiculo  VARCHAR(8)   NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_entregador_cpf (cpf),
  UNIQUE KEY uq_entregador_cnh (cnh),
  CONSTRAINT ck_entregador_cpf CHECK (cpf REGEXP '^[0-9]{11}$')
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 6) Agendamento
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agendamento (        -- [AJUSTE] (era lojas_agendamento)
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  cliente_id       INT UNSIGNED NOT NULL,       -- [AJUSTE] era opcional
  animal_id        INT UNSIGNED NOT NULL,       -- [AJUSTE] era opcional
  veterinario_id   INT UNSIGNED NOT NULL,       -- [NOVO]
  recepcionista_id INT UNSIGNED NULL,           -- [IGUAL] preenchido quando a recepcao confirma
  tipo   ENUM('consulta','exame','cirurgia') NOT NULL,                     -- [NOVO]
  data_hora DATETIME NOT NULL,                                             -- [NOVO]
  status ENUM('agendado','confirmado','cancelado','concluido','nao_compareceu')
         NOT NULL DEFAULT 'agendado',           -- [AJUSTE] substitui "confirmacao" (true = 'confirmado')
  observacao VARCHAR(500) NULL,                 -- [NOVO]
  criado_em  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,                  -- [NOVO]
  -- Horario "ocupado": so existe enquanto o agendamento esta ativo.
  -- Com a chave unica abaixo, o BANCO impede dois agendamentos ativos no mesmo
  -- horario do mesmo veterinario. Cancelar libera o horario.   -- [NOVO]
  horario_ocupado DATETIME GENERATED ALWAYS AS (
    CASE WHEN status IN ('agendado','confirmado','concluido') THEN data_hora END
  ) STORED,
  PRIMARY KEY (id),
  UNIQUE KEY uq_agenda_veterinario_horario (veterinario_id, horario_ocupado),
  KEY ix_agendamento_data (data_hora),
  CONSTRAINT fk_agenda_veterinario   FOREIGN KEY (veterinario_id)   REFERENCES veterinario (id),
  CONSTRAINT fk_agenda_recepcionista FOREIGN KEY (recepcionista_id) REFERENCES recepcionista (id),
  -- [NOVO] O animal TEM que pertencer ao cliente (via perfil_pet): o agente
  -- nao consegue agendar para o pet de outra pessoa.
  CONSTRAINT fk_agenda_dono_animal   FOREIGN KEY (cliente_id, animal_id)
                                     REFERENCES perfil_pet (cliente_id, animal_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 7) Pedido, itens e pagamento
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pedido (             -- [AJUSTE] (era lojas_pedido)
  id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
  cliente_id        INT UNSIGNED NOT NULL,      -- [AJUSTE] era opcional
  loja_id           INT UNSIGNED NULL,          -- [NOVO] loja que atende o pedido
  entregador_id     INT UNSIGNED NULL,          -- [NOVO]
  status ENUM('carrinho','aguardando_pagamento','pago','em_separacao',
              'em_entrega','entregue','cancelado')
         NOT NULL DEFAULT 'carrinho',           -- [AJUSTE] substitui "finalizado" (false = 'carrinho')
  codigo_transacao  VARCHAR(200) NULL,          -- [IGUAL]
  endereco_entrega  VARCHAR(255) NULL,          -- [AJUSTE] coluna era "endereco"; texto fixado na compra
  data_finalizacao  DATETIME NULL,              -- [IGUAL]
  criado_em         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- [NOVO]
  PRIMARY KEY (id),
  KEY ix_pedido_status (status),
  KEY ix_pedido_codigo (codigo_transacao),
  CONSTRAINT fk_pedido_cliente    FOREIGN KEY (cliente_id)    REFERENCES cliente (id),
  CONSTRAINT fk_pedido_loja       FOREIGN KEY (loja_id)       REFERENCES loja (id),
  CONSTRAINT fk_pedido_entregador FOREIGN KEY (entregador_id) REFERENCES entregador (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS itens_pedido (       -- [AJUSTE] (era lojas_itenspedido)
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  pedido_id        INT UNSIGNED NOT NULL,       -- [AJUSTE] era opcional
  item_estoque_id  INT UNSIGNED NOT NULL,       -- [AJUSTE] era opcional
  quantidade       INT UNSIGNED NOT NULL,       -- [IGUAL] precisa ser maior que zero
  preco_unitario   DECIMAL(10,2) NOT NULL,      -- [NOVO] preco no momento da compra (historico nao muda)
  PRIMARY KEY (id),
  UNIQUE KEY uq_item_por_pedido (pedido_id, item_estoque_id),  -- [NOVO] mesmo item = uma linha so
  CONSTRAINT ck_itens_quantidade CHECK (quantidade > 0),
  CONSTRAINT ck_itens_preco      CHECK (preco_unitario >= 0),
  CONSTRAINT fk_itens_pedido  FOREIGN KEY (pedido_id)       REFERENCES pedido (id),
  CONSTRAINT fk_itens_estoque FOREIGN KEY (item_estoque_id) REFERENCES item_estoque (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pagamento (          -- [AJUSTE] (era lojas_pagamento)
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  pedido_id     INT UNSIGNED NOT NULL,          -- [AJUSTE] era opcional
  id_pagamento  VARCHAR(100) NOT NULL,          -- [AJUSTE] codigo do pagamento no gateway; agora unico
  aprovado      BOOLEAN NOT NULL DEFAULT 0,     -- [IGUAL] um pedido pode ter varias tentativas
  criado_em     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- [NOVO]
  PRIMARY KEY (id),
  UNIQUE KEY uq_pagamento_gateway (id_pagamento),
  KEY ix_pagamento_pedido (pedido_id),
  CONSTRAINT fk_pagamento_pedido FOREIGN KEY (pedido_id) REFERENCES pedido (id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 8) Banners da vitrine (no e-commerce se chamava "petshop")
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS petshop (            -- [IGUAL] (era lojas_petshop)
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  imagem        VARCHAR(100) NULL,              -- [IGUAL]
  link_destino  VARCHAR(400) NULL,              -- [IGUAL]
  ativo         BOOLEAN NOT NULL DEFAULT 1,     -- [IGUAL]
  PRIMARY KEY (id)
) ENGINE=InnoDB;