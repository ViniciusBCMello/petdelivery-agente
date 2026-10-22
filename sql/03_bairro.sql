-- Passo 4A: tabela de bairros (ponto de referencia para "loja mais proxima")
USE petdelivery_agente;

CREATE TABLE IF NOT EXISTS bairro (          -- [NOVO]
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nome       VARCHAR(100) NOT NULL,
  cidade     VARCHAR(100) NOT NULL,
  estado     CHAR(2)      NOT NULL,
  latitude   DECIMAL(9,6) NOT NULL,          -- centro aproximado do bairro
  longitude  DECIMAL(9,6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_bairro (nome, cidade)
) ENGINE=InnoDB;