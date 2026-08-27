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

-- pgvector extension + legal_kb_embeddings (AWS deploy, PGV-2/PGV-4)
-- This file is split on semicolons by Database.apply_schema, so every
-- statement below must stay free of internal semicolons and idempotent
-- No vector index on embedding: pgvector caps both HNSW and IVFFlat at 2000
-- dims (verified on 0.8.6) and gemini-embedding-001 emits 3072 dims, so no
-- index is possible on the raw vector. The corpus is tiny and read-mostly
-- (seeded once), so an exact sequential scan is fast and correct. If the
-- corpus grows, switch to a sub-2000-dim embedding model and add HNSW.
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