-- db/init.sql — LexBot case database schema (idempotent).
-- Applied via compose initdb mount on fresh volumes AND at api startup (D5).
-- Re-running MUST NOT error or duplicate (DB-1).

CREATE TABLE IF NOT EXISTS cases (
    id SERIAL PRIMARY KEY,
    case_number TEXT UNIQUE,
    client_name TEXT,
    status TEXT DEFAULT 'open',
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS follow_ups (
    id SERIAL PRIMARY KEY,
    case_id INT REFERENCES cases(id),
    description TEXT,
    due_date DATE,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- pgvector extension + legal_kb_embeddings (AWS deploy: store migration, PGV-2/PGV-4).
-- NOTE: this file is split on ';' by Database.apply_schema(), so no statement
-- below may contain an internal semicolon. All statements are idempotent.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS legal_kb_embeddings (
    id BIGSERIAL PRIMARY KEY,
    chunk_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    embedding vector(3072) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS legal_kb_embeddings_embedding_idx
    ON legal_kb_embeddings USING hnsw (embedding vector_cosine_ops);