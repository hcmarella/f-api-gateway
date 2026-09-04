-- forge-api-gateway core schema
-- Requires the pgvector extension (see db/init/00_extensions.sql)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Core org / identity
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS teams (
    team_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id     TEXT NOT NULL REFERENCES teams(team_id),
    email       TEXT NOT NULL UNIQUE,
    persona     TEXT NOT NULL DEFAULT 'business', -- e.g. business, developer, admin
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Conversations
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT NOT NULL REFERENCES teams(team_id),
    user_id         UUID REFERENCES users(user_id),
    title           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    message_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id       UUID NOT NULL REFERENCES conversations(conversation_id),
    role                  TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content                TEXT NOT NULL,
    triage_route           TEXT,          -- which agent graph branch handled this
    confidence             DOUBLE PRECISION,
    retry_count            INT DEFAULT 0,  -- schema-ready; not yet populated by app code
    retrieval_engine_used  TEXT,           -- schema-ready; not yet populated
    gates_fired            JSONB,          -- schema-ready; not yet populated
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS message_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL, -- e.g. knowledge_chunk, jira, confluence, sharepoint
    source_ref      TEXT NOT NULL, -- chunk_id, jira issue key, url, etc.
    title           TEXT,
    url             TEXT,
    score           DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Documents & knowledge (RAG)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS documents (
    document_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT NOT NULL REFERENCES teams(team_id),
    source_type     TEXT NOT NULL DEFAULT 'local_md', -- local_md, confluence, sharepoint, ...
    source_ref      TEXT NOT NULL, -- file path / page id / url
    title           TEXT,
    checksum        TEXT,
    repo_or_space   TEXT,          -- e.g. github repo or Confluence space key
    commit_sha      TEXT,
    classification  TEXT NOT NULL DEFAULT 'internal',
    deleted_at      TIMESTAMPTZ,   -- soft delete only
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (team_id, source_type, source_ref)
);

-- Okta-group-based document access. document_id stays UUID (matches
-- documents.document_id) rather than the memory-model spec's TEXT, since
-- changing the PK type there would break knowledge_chunks' FK and
-- app/ingestion/local_md_ingest.py's gen_random_uuid()-based inserts.
CREATE TABLE IF NOT EXISTS access_control (
    document_id     UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    okta_group      TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'read',
    PRIMARY KEY (document_id, okta_group)
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id            TEXT PRIMARY KEY,
    team_id             TEXT NOT NULL REFERENCES teams(team_id),
    document_id         UUID REFERENCES documents(document_id) ON DELETE CASCADE,
    content             TEXT NOT NULL,
    embedding           VECTOR(768) NOT NULL, -- matches BAAI/bge-base-en-v1.5 output dim
    chunk_index         INT NOT NULL DEFAULT 0,
    token_count         INT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(), -- powers the Freshness gate
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_team ON knowledge_chunks(team_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Skills / personas
-- ---------------------------------------------------------------------------

-- Metadata index only — content stays in knowledge/skills/*.md (source_path).
-- Router uses this to *find* a skill fast; the skill's actual instructions
-- are never retrieved from this table, only from the file on disk.
CREATE TABLE IF NOT EXISTS persona_index (
    persona_id      TEXT PRIMARY KEY,          -- matches the skill's frontmatter `id`
    name            TEXT NOT NULL,
    description     TEXT,
    persona_access  TEXT[] NOT NULL DEFAULT '{}',
    triggers        TEXT[] DEFAULT '{}',
    when_to_use     TEXT,
    team_id         TEXT NOT NULL DEFAULT 'all',  -- 'all' = shared across teams
    source_path     TEXT NOT NULL,
    embedding       VECTOR(768),                  -- semantic fallback only; never
                                                   -- used to retrieve instructions
    approved_by     TEXT,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_persona_index_team ON persona_index(team_id);
CREATE INDEX IF NOT EXISTS idx_persona_index_embedding
    ON persona_index USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Governance / audit
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT,
    actor           TEXT,          -- user_id, 'system', or agent node name
    action          TEXT NOT NULL,
    target          TEXT,
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS content_review_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT NOT NULL REFERENCES teams(team_id),
    target          TEXT NOT NULL, -- e.g. new_skill, chunk_edit
    proposed_content TEXT NOT NULL,
    context         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    submitted_by    TEXT NOT NULL DEFAULT 'system:draft_skill_node', -- or a user_id, once humans can submit directly
    reviewer        TEXT,
    reviewed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT NOT NULL REFERENCES teams(team_id),
    connector       TEXT NOT NULL, -- local_md, confluence, sharepoint, jira
    status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
    documents_processed INT NOT NULL DEFAULT 0,
    chunks_upserted INT NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS skill_gap_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT NOT NULL REFERENCES teams(team_id),
    conversation_id UUID REFERENCES conversations(conversation_id),
    question        TEXT NOT NULL,
    triage_result   JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_queue_id UUID REFERENCES content_review_queue(id),
    occurred_count  INT DEFAULT 1,   -- schema-ready; not yet populated by app code
    user_role       TEXT,            -- schema-ready; not yet populated
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_case_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         TEXT NOT NULL REFERENCES teams(team_id),
    question        TEXT NOT NULL,
    retrieval_engine TEXT NOT NULL, -- pgvector, neo4j
    confidence      DOUBLE PRECISION,
    latency_ms      DOUBLE PRECISION,
    passed          BOOLEAN,
    details         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
