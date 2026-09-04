# forge-api-gateway

FastAPI + pgvector RAG/agent gateway. Owns all domain data (the only
Postgres), all retrieval, all routing decisions, and all connector calls.
The frontend (`Forge-UI`, sibling repo) owns nothing but rendering — see
[Frontend + BFF communication](#frontend--bff-communication) below.

```text
                     ┌─────────────────────────────────────────────┐
browser ──> Forge-UI │  Vite dev server / static build              │
 (:5173/5174)        └───────────────────┬───────────────────────────┘
                                          │ fetch (same-origin to the BFF)
                     ┌───────────────────▼───────────────────────────┐
                     │  bff/server.mjs (stateless, Forge-UI repo)     │  :4000
                     │  proxies a fixed endpoint allowlist,           │
                     │  attaches identity headers (stubbed today)     │
                     └───────────────────┬───────────────────────────┘
                                          │ server-to-server HTTP
                     ┌───────────────────▼───────────────────────────┐
                     │  forge-api-gateway (this repo)                 │  :8001→8000
                     │  FastAPI + LangGraph                           │
                     └──────┬──────────┬───────────────┬─────────────┘
                             │          │               │
                     ┌───────▼──┐  ┌────▼────┐   ┌──────▼───────┐
                     │ Postgres │  │  Redis  │   │  Neo4j (test │
                     │ +pgvector│  │         │   │  lane only)  │
                     └──────────┘  └─────────┘   └──────────────┘
```

## Request flow (the agent graph)

Every `POST /ai/chat` runs through `app/agents/graph.py`, a LangGraph state
machine:

```text
triage (rule-based classifier)
   │
   ├─ skill_match ──┐
   ├─ rag_node ──────┤  if the first branch tried doesn't confidently
   ├─ live_data_node │  match, the OTHER knowledge branch (skill_match <->
   └─ (see below)    │  rag_node) is tried as a second pass
                      │
              both fail? ──> draft_skill (logs the gap, stages a proposed
                              skill for human review, returns a graceful
                              fallback — NEVER writes to knowledge/skills/
                              directly)
                      │
                      ▼
                 synthesize (still a mock string — no model credential
                 wired up yet, see "What's real vs mocked" below)
                      │
                      ▼
                    gates (placeholder pass-through today)
                      │
                      ▼
                 eval_score (placeholder — real scoring happens in
                 eval_case_log via test/graphdb_comparison.py)
```

`live_data_node` dispatches to Jira (sprint/ticket questions) or SharePoint
(document-search questions, delegated OAuth) live at query time.
Confluence is the odd one out — content-wise it behaves like documentation,
so it's ingested and embedded (`app/ingestion/confluence_ingest.py`) rather
than called live. See `app/connectors/` for all three; all three mock the
actual HTTP call (no live credentials in this environment) behind a real,
swappable interface.

## Quickstart

```bash
docker compose up -d --build          # gateway + postgres(pgvector) + redis
curl -s http://localhost:8001/health/deep
# {"postgres":"ok","redis":"ok"}

docker compose exec -T postgres psql -U forge -d forge < db/schema.sql   # < is a host-shell redirect —
                                                                           # the postgres container doesn't
                                                                           # have the repo mounted, so -f won't work here
docker compose exec -T gateway python -m app.ingestion.local_md_ingest \
  --knowledge-dir knowledge/docs --team-id test

# optional: use a real Claude response instead of the default mock synthesizer
export ANTHROPIC_API_KEY=your-key
export LLM_MODE=real
docker compose up -d --build gateway

curl -s -X POST http://localhost:8001/ai/chat -H "Content-Type: application/json" \
  -d '{"question":"What is our policy on data retention?","team_id":"test","persona":"business"}'
```

Live ops view while you're testing: **http://localhost:8001/dashboard**
(routing distribution, review queue, sync pipeline, pgvector-vs-Neo4j eval
comparison, audit log — polls `GET /admin/stats` every 15s, own page,
nothing to do with Forge-UI).

Optional: the Neo4j graph test lane (never part of the main stack —
`docker-compose.test.yml`'s own header says so):

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d neo4j-test
docker compose exec -T gateway python test/graphdb_comparison.py         # pgvector vs neo4j, real numbers
docker compose exec -T gateway python test/test_graph_entity_ingestion.py # entity graph (Project/Ticket/...), real multi-hop query
```

## API reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness only |
| `GET` | `/health/deep` | Confirms live Postgres + Redis connections |
| `POST` | `/ai/chat` | Runs a question through the agent graph. Body: `{question, team_id, persona, user_email, conversation_id?}`. Returns `{answer, route, sources, gate_passed, score, conversation_id, message_id}` |
| `GET` | `/admin/review-queue?team_id=` | Pending `content_review_queue` entries for a team |
| `POST` | `/admin/review-queue/{id}/approve-skill` | Writes the skill file to `knowledge/skills/{team}/`, git-commits it. Body: `{edited_content?, reviewer?, role}` — **`role` must be `admin` or `super_user`, 403 otherwise** (see Security below) |
| `POST` | `/admin/review-queue/{id}/reject` | Body: `{reviewer?, reason?, role}` — same role requirement |
| `GET` | `/admin/stats` | Everything the dashboard renders, as JSON |
| `GET` | `/dashboard` | The ops dashboard page itself |

## Frontend + BFF communication

The browser never talks to this gateway directly — it only ever talks to
Forge-UI's BFF (`bff/server.mjs`, sibling repo), which proxies a fixed
allowlist of routes here over a plain server-to-server HTTP call (no CORS
involved, since browser-to-BFF and BFF-to-gateway are two different hops).

**Local dev, everything on the host** (simplest — what this session used):

```bash
# this repo, already up per Quickstart above, gateway on :8001

# in the Forge-UI repo:
GATEWAY_BASE_URL=http://localhost:8001 PORT=4000 node bff/server.mjs   # terminal 1
VITE_API_BASE_URL=http://localhost:4000 npm run dev                    # terminal 2 (echo into .env or export)
```

Open the Vite URL it prints (5173, or 5174 if 5173 is taken). Every chat
message and review-queue action now round-trips through the real gateway,
not `mock-gateway`.

**Docker Compose on both sides**: the two repos are separate compose
projects, so there's no shared Docker network by default. Either:
- run the BFF outside Docker as above (talks to `localhost:8001`, the
  gateway's host-published port), or
- if the BFF runs in Forge-UI's own compose stack, point it at
  `host.docker.internal:8001` (Docker Desktop's route from a container back
  to the host), not `localhost` — that's the single most common cause of
  "works in curl, fails in the browser" in this exact split-repo setup.

**Contract**: `app/api/chat.py`'s `ChatRequest`/`ChatResponse` Pydantic
models are the source of truth. Forge-UI's `src/schemas/ai_response.ts` and
`src/types/review.ts` mirror them by hand — if you change a field here,
update those too (there's no shared/generated type package yet).

**Identity**: the BFF currently sends stub `X-Forge-User-Id`/`X-Forge-Team-Id`
headers this gateway doesn't read — `team_id`/`persona`/`user_email` come
straight from the request body, trusted at face value. There is no
authentication system. See `docs/BUILD_SUMMARY.md` Phase 7.

## Testing

Two suites, deliberately different in kind:

**`test/`** — plain runnable scripts, print real PASS/FAIL and real
numbers when you run them directly. Use these to eyeball what the system
actually does:

```bash
docker compose exec -T gateway python test/test_embed_similarity.py    # BGE calibration: paraphrase >0.85, unrelated <0.4
docker compose exec -T gateway python test/test_graph_routing.py       # triage routes to the correct branch
docker compose exec -T gateway python test/test_rag_retrieval.py       # pgvector confidence calibration
docker compose exec -T gateway python test/test_skill_match_persona.py # persona filtering both directions
docker compose exec -T gateway python test/test_draft_skill.py         # fallback fires, never writes knowledge/skills/ directly
docker compose exec -T gateway python test/test_rbac_leakage.py        # tenant isolation, 12 checks
docker compose exec -T gateway python test/graphdb_comparison.py       # pgvector vs neo4j, needs neo4j-test up
docker compose exec -T gateway python test/test_graph_entity_ingestion.py  # entity graph + multi-hop query, needs neo4j-test up
```

**`tests/`** — real pytest, covering data leakage, GraphDB-vs-vector,
confidence calibration, token savings, and security (TC-1.x through
TC-5.x):

```bash
docker compose exec -T gateway pytest tests/ -v
```

Last real run: **15 passed, 10 skipped, 3 xfailed** — every skip/xfail has
an inspectable reason in the test itself (mocked `synthesize()`, no auth
system, no longitudinal eval data), never a silent no-op. Writing this
suite found and fixed three real bugs (a logged OAuth token, an
unpopulated `audit_log` table, zero authorization on the admin endpoints)
— see the commit history for `tests/test_security.py` and
`app/audit.py` if you want the details.

**CI**: `.github/workflows/ci.yml` runs the full `test/` sequence plus
`pytest tests/` on every PR touching `app/agents/`, `app/rag/`,
`app/connectors/`, `app/ingestion/`, the schema, or requirements.
`test_graphdb_vs_vector.py` self-skips there (no Neo4j service stood up in
CI — that comparison is a local/manual decision-support tool, not a
permanent gate).

**Watch it happen**: run any of the above against the running gateway,
then refresh `/dashboard` — the routing distribution, recent messages, and
audit log update live.

## What's real vs mocked

Full honest accounting (phase-by-phase against the original architecture
doc, every shortcut flagged) lives in `docs/BUILD_SUMMARY.md` — short
version:

- **Real**: pgvector retrieval, embeddings, agent graph routing, persona
  filtering, the skill-approval git-commit flow, tenant isolation, audit
  logging, the admin role check, the Neo4j entity graph and its multi-hop
  query.
- **Mocked, real interface**: Jira/Confluence/SharePoint's actual HTTP
  calls (no live credentials in this environment) — swappable without
  changing any caller.
- **Not built yet**: the real model call behind `synthesize()` (no
  Bedrock/Anthropic credential), the 6 governance gates from the
  architecture doc (currently one pass-through node), real authentication,
  a ServiceNow connector, a reports service.

## Repo layout

```text
app/
  agents/        LangGraph state machine, skill matching, draft_skill node
  admin/         review-queue approve/reject, GET /admin/stats
  api/           POST /ai/chat
  connectors/    jira/confluence/sharepoint — mocked HTTP, real interface
  graph/         Neo4j entity-relationship test lane (Project/Ticket/...)
  ingestion/     local markdown + Confluence -> knowledge_chunks
  rag/           embedding model wrapper (BAAI/bge-base-en-v1.5)
  audit.py       central audit_log writer
db/schema.sql    14-table schema (pgvector, tenant-scoped throughout)
knowledge/       docs/ (RAG corpus) + skills/ (persona-filtered, git-native)
static/          dashboard.html
test/            runnable scripts, real output
tests/           pytest — leakage/graphdb/confidence/tokens/security
docs/            BUILD_SUMMARY.md, DEV_EKS_REQUEST_DRAFT.md
```
