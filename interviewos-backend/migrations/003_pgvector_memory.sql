DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN undefined_file OR insufficient_privilege THEN
        RAISE NOTICE 'pgvector extension is not available; keeping agent_memories.embedding JSONB fallback.';
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        EXECUTE 'ALTER TABLE agent_memories ADD COLUMN IF NOT EXISTS embedding_vector vector(384)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_agent_memories_embedding_vector ON agent_memories USING ivfflat (embedding_vector vector_cosine_ops)';
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_memories_privacy_scope ON agent_memories(user_id, privacy_scope);
