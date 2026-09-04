-- V2: memory-model upgrade (procedural / semantic / episodic / graph / growth).
--
-- This is a DELIBERATE ADAPTATION of the "Memory Data Model — Final" spec, not
-- a literal transcription. The spec's raw CREATE TABLE statements assume a
-- fresh database; this one already has live data (real ingested
-- knowledge_chunks, real pending content_review_queue rows from draft_skill),
-- so several of the spec's proposed changes are intentionally NOT applied
-- as-is. Each deviation is called out below with why.
--
-- Applied: persona_index, access_control fully replaced (confirmed empty and
-- unread by any code — see git history for the verification query).
-- Applied additively: documents/knowledge_chunks/content_review_queue gain
-- new columns; nothing existing is renamed or dropped.
--
-- NOT applied (spec vs. reality conflicts, left for a follow-up if still wanted):
--   - documents.document_id TEXT (spec) vs UUID (live): changing the PK type
--     would break knowledge_chunks.document_id's FK and
--     app/ingestion/local_md_ingest.py, which relies on gen_random_uuid().
--   - content_review_queue.id -> review_id, context -> metadata,
--     reviewer -> reviewed_by: the API already returns "review_id" in JSON
--     (app/admin/review_queue.py maps id -> review_id at the response layer),
--     so the external contract the spec cares about already holds. Renaming
--     the underlying column buys nothing and would require touching
--     review_queue.py, draft_skill.py, and the skill_gap_log FK simultaneously
--     on a table with real pending rows right now — not worth the risk for a
--     purely cosmetic rename.
--   - message_sources shrinking to (document_id, chunk_id, relevance_score):
--     would drop source_type/title/url, which are real, populated, and still
--     needed for jira/sharepoint sources that have no document_id at all.
--   - skill_gap_log redesign (dropping review_queue_id/conversation_id FKs
--     for an occurred_count column): the current FK linking a gap to the
--     review-queue row it produced is actively used and more useful than a
--     dedup counter; not replacing it without a clearer case for the trade.
--   - graph schema: Neo4j, not Postgres — already handled entirely in
--     app/graph/, out of scope for a SQL migration.

BEGIN;

-- ---------------------------------------------------------------------------
-- Procedural memory: persona_index. Confirmed empty, confirmed unread by any
-- code (skill_match.py reads knowledge/skills/*.md directly from disk) —
-- safe to replace the shape outright instead of ALTERing piecemeal.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS persona_index;

CREATE TABLE persona_index (
    persona_id      TEXT PRIMARY KEY,          -- matches the skill's frontmatter `id`
    name            TEXT NOT NULL,
    description     TEXT,
    persona_access  TEXT[] NOT NULL DEFAULT '{}',
    triggers        TEXT[] DEFAULT '{}',
    when_to_use     TEXT,
    team_id         TEXT NOT NULL DEFAULT 'all',  -- 'all' = shared across teams
    source_path     TEXT NOT NULL,                -- path under knowledge/skills/
    embedding       VECTOR(768),                  -- semantic fallback ONLY when
                                                   -- trigger phrases miss; the
                                                   -- skill's actual instructions
                                                   -- are never retrieved from here
    approved_by     TEXT,                         -- git commit author, if via draft-skill flow
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_persona_index_team ON persona_index(team_id);
CREATE INDEX idx_persona_index_embedding ON persona_index USING hnsw (embedding vector_cosine_ops);

-- Nothing populates this table yet (a future sync step — walk
-- knowledge/skills/**/*.md and upsert — is not part of this migration).

-- ---------------------------------------------------------------------------
-- access_control: also confirmed empty and unread by any code. Adopting the
-- spec's (document_id, okta_group) composite-key shape, but keeping
-- document_id as UUID to match the live documents table (see note above on
-- why documents.document_id isn't being changed to TEXT).
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS access_control;

CREATE TABLE access_control (
    document_id  UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    okta_group   TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'read',
    PRIMARY KEY (document_id, okta_group)
);

-- ---------------------------------------------------------------------------
-- Semantic memory: documents / knowledge_chunks — additive only, PK/FK types
-- and existing columns untouched so local_md_ingest.py and rag_node keep
-- working unmodified.
-- ---------------------------------------------------------------------------

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS repo_or_space TEXT,
    ADD COLUMN IF NOT EXISTS commit_sha TEXT,
    ADD COLUMN IF NOT EXISTS classification TEXT NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- source_updated_at now powers a real freshness penalty in rag_node
-- (_freshness_factor, app/agents/graph.py) — not a decorative column.
-- Defaulted to now() so it's NOT NULL from day one without a fabricated
-- backfill value for pre-existing chunks (honest: we don't know their true
-- source update time, so "ingested now" is the least-wrong default).
-- local_md_ingest.py passes the real file mtime; confluence_ingest.py
-- passes the mock connector's last_modified field. Verified end-to-end:
-- see tests/test_confidence.py::test_tc3_3_stale_source_confidence_penalty.
ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS source_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- ---------------------------------------------------------------------------
-- Growth mechanism: content_review_queue gains submitted_by. Backfilled to
-- 'system:draft_skill_node' because that node is currently the ONLY writer
-- of this table (verified in app/agents/nodes/draft_skill.py) — every
-- existing row really was submitted by it.
-- ---------------------------------------------------------------------------

ALTER TABLE content_review_queue
    ADD COLUMN IF NOT EXISTS submitted_by TEXT NOT NULL DEFAULT 'system:draft_skill_node';

-- ---------------------------------------------------------------------------
-- Episodic memory: capture what the graph already computes internally
-- (the skill_match<->rag_node cascading retry, which engine answered) but
-- never persisted. Schema-ready; app/api/chat.py does not populate these
-- yet — see docs/BUILD_SUMMARY.md for the honest "not wired up" note rather
-- than pretending this is finished.
-- ---------------------------------------------------------------------------

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS retry_count INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS retrieval_engine_used TEXT,
    ADD COLUMN IF NOT EXISTS gates_fired JSONB;

ALTER TABLE skill_gap_log
    ADD COLUMN IF NOT EXISTS occurred_count INT DEFAULT 1,
    ADD COLUMN IF NOT EXISTS user_role TEXT;

COMMIT;
