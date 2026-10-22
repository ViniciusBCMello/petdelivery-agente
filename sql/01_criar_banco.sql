CREATE DATABASE IF NOT EXISTS petdelivery_agente
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- Troque a senha abaixo por uma sua (e use a mesma no arquivo .env).
CREATE USER IF NOT EXISTS 'petdelivery_app'@'localhost'
  IDENTIFIED BY '91MzEqZ+Yd6shW/7uRQzMDy25agoMWFls5WNA4jpe6U=';

-- Zera permissoes antigas (caso o usuario ja exista de uma tentativa anterior).
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'petdelivery_app'@'localhost';

-- Privilegio minimo, e SO no banco do agente.
GRANT SELECT, INSERT, UPDATE, DELETE ON petdelivery_agente.* TO 'petdelivery_app'@'localhost';
FLUSH PRIVILEGES;