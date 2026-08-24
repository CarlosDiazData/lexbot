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