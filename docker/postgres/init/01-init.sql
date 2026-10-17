-- Runs once, when the data volume is first created (docker-entrypoint-initdb.d).
-- The entrypoint connects to $POSTGRES_DB as $POSTGRES_USER (superuser).

-- Dev database: pgvector for the embedding column.
CREATE EXTENSION IF NOT EXISTS vector;

-- Integration-test database, kept separate so tests never touch dev data.
CREATE DATABASE dataforce_test;
\connect dataforce_test
CREATE EXTENSION IF NOT EXISTS vector;
