-- Supabase SQL schema for case study vector search
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor > New Query)

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create case_studies table
CREATE TABLE IF NOT EXISTS case_studies (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL DEFAULT '',
    use_case TEXT NOT NULL DEFAULT '',
    doc_type TEXT NOT NULL DEFAULT '',
    content_text TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    embedding VECTOR(1024),
    metadata JSONB DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Create IVFFlat index for cosine similarity (lists=15 is good for ~228 rows)
CREATE INDEX IF NOT EXISTS case_studies_embedding_idx
    ON case_studies
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 15);

-- 4. Create RPC function for similarity search
CREATE OR REPLACE FUNCTION match_case_studies(
    query_embedding VECTOR(1024),
    match_count INT DEFAULT 5,
    match_threshold FLOAT DEFAULT 0.0
)
RETURNS TABLE (
    id BIGINT,
    filename TEXT,
    company_name TEXT,
    use_case TEXT,
    doc_type TEXT,
    summary TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        cs.id,
        cs.filename,
        cs.company_name,
        cs.use_case,
        cs.doc_type,
        cs.summary,
        1 - (cs.embedding <=> query_embedding) AS similarity
    FROM case_studies cs
    WHERE cs.embedding IS NOT NULL
      AND 1 - (cs.embedding <=> query_embedding) > match_threshold
    ORDER BY cs.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
