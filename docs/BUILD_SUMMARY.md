# Build Summary — what's actually implemented vs. spec

Written after the initial build session. Compares against both specs this
repo was built to: the original 12-step task list, and the later
`ARCHITECTURE.md` §5 build order (which formalized/extended the same intent).
Every "done" claim below has a corresponding real command run and real
output shown during the build — see the session transcript, or re-run
`test/*.py` yourself. Nothing here is marked done on the basis of code review
alone.

## Status by ARCHITECTURE.md §5 phase

| # | Phase | Status | Notes |
|---|---|---|---|
| 0 | docker-compose reproducible: gateway + BFF + Postgres+pgvector + mock connectors | **Done** | Gateway repo's docker-compose.yml (gateway/postgres/redis); UI repo separately runs BFF+mock-gateway+ui. Two separate compose projects, not one merged stack — see "Known gaps" below. |
| 1 | Freeze the AIResponse contract as a shared schema | **Partially done, diverged from spec** | The *actual* contract (`answer/route/sources/gate_passed/score/conversation_id/message_id`) is simpler than ARCHITECTURE.md §3's aspirational one (`type/actions/confidence/metadata.*`). The UI was built against the real contract, not the doc's. No `app/schemas/ai_response.py` Pydantic model exists yet — the contract lives only as inline Pydantic classes in `app/api/chat.py`. |
| 2 | `/ai/chat` with mock Intent Router + mock Source Router + mock citations | **Done** | `triage()` is a rule-based mock; `skill_match`/`rag_node` are real, not mocked, as of phase 4 below. |
| 3 | UI renders sources/actions/type from the mock | **Done (sources only — no `actions`/`type` fields exist)** | UI renders `sources`; there's no `actions` array or `type` discriminator in the real contract, so that part of the UI (if built for it) has nothing to render. |
| 4 | pgvector + embeddings, tested against 10-20 real files | **Done** | 13 real markdown files, BGE-base-en-v1.5, 768-dim, cosine thresholds calibrated with real numbers (paraphrase >0.85, unrelated <0.4). |
| 5 | Real Bedrock call replaces the mock synthesis | **NOT done — blocked** | No AWS/Bedrock credentials or ANTHROPIC_API_KEY in this environment. `synthesize()` in `app/agents/graph.py` still returns a fixed mock string. User explicitly chose to defer this rather than have it faked. |
| 6 | Skills registry (SKILL.md discovery) | **Done** | `app/agents/skill_match.py`, persona-filtered, YAML frontmatter, real test coverage both directions (business/developer). |
| 7 | Okta/AD authorization + permission-filtered retrieval | **NOT done** | The gateway trusts `team_id`/`persona`/`user_email` straight from the request body. The UI's BFF sends stub identity headers (`X-Forge-User-Id: stub-user`) that the gateway doesn't read. Retrieval **is** permission-filtered by `team_id`/`persona` (see the RBAC suite), but the identity feeding those fields isn't verified by anything yet — a caller can claim any team/persona it wants. |
| 8 | Live connectors: Jira → Confluence → ServiceNow → SharePoint | **3 of 4 done** | Jira (live) and SharePoint (live, delegated OAuth) done; Confluence (embed path) done. **ServiceNow was never built** — not in the original 12-step task either; it only appears in ARCHITECTURE.md. All three built connectors mock the actual HTTP call (no live credentials available) but the interface/dispatch logic is real and tested. |
| 9 | Reports service | **NOT done** | No `content_review_queue` target other than `new_skill` is handled; no report generation exists anywhere in the codebase. |
| 10 | Move to DEV (EKS) | **NOT done — not actionable by me** | No AWS/EKS access. See the DEV EKS request draft below — this needs a human to file it. |
| 11 | RBAC/leakage test suite in CI | **Done** | `test/test_rbac_leakage.py` (12/12 real checks) + `.github/workflows/ci.yml` running it (and the eval suite) on every PR touching `app/agents/`, `app/rag/`, `app/connectors/`, `app/ingestion/`, schema, or requirements. |
| 12 | STG → PROD | **NOT done** | Not reachable before phase 10. |

## The 6 Governance Gates (ARCHITECTURE.md §2)

Permission, Evidence, Freshness, Quality, Action, Memory — the `gates` node
in `app/agents/graph.py` is currently a single unconditional pass-through
(`{"gate_passed": True, "gate_reason": "no gating rules enforced yet"}`). None
of the six are implemented as real checks. This is the largest gap between
"what the architecture calls for" and "what exists" that isn't blocked on a
credential — it's just not built yet.

## Explicit shortcuts and deviations (flagged, not hidden)

- **RAG threshold is empirically calibrated, not theory-derived.** 0.55 was
  picked by running real relevant/nonsense questions against the actual
  corpus and finding the gap between clusters (relevant: 0.55–0.79, nonsense:
  ~0.40–0.42). It will need recalibration if the corpus changes shape
  significantly (many more documents, very short documents, etc.).
- **Chunking uses word-count as a token proxy**, not a real tokenizer
  (`app/ingestion/local_md_ingest.py:approx_tokenize`). Fine for English
  prose at this corpus size; will drift from true token counts if content
  becomes token-dense (code, non-English text).
- **All three connectors (Jira/Confluence/SharePoint) mock the actual network
  call.** The dispatch/routing/interface logic is real and tested; the
  `_call_*_api` functions are explicitly-labeled stand-ins. Swapping in real
  credentials should not require changing any caller.
- **`gates` and the 6 governance gates it's supposed to represent do not
  exist yet** — see above.
- **No real authentication.** Every request is trusted at face value for
  `team_id`/`persona`/`user_email`. The RBAC suite proves tenant *data*
  isolation holds once those fields are set correctly — it does not prove
  a malicious caller can't just set them to someone else's team.
- **Two separate docker-compose projects, not one.** ARCHITECTURE.md phase 0
  implies one reproducible stack (portal + BFF + gateway + Postgres + mock
  connectors). In practice the gateway repo and UI repo each have their own
  compose file; connecting them requires manually pointing `GATEWAY_BASE_URL`
  at the gateway's host-published port (or `host.docker.internal` from
  inside the UI's compose network). Documented, but not automated.
- **`ARCHITECTURE.md` itself only lives in the UI repo**, despite its own
  header instructing it to live in both, as `docs/ARCHITECTURE.md`. Not yet
  copied here.

## What's solid

Everything marked "Done" above has a real, re-runnable test behind it:
`test/test_embed_similarity.py`, `test/test_graph_routing.py`,
`test/test_rag_retrieval.py`, `test/test_skill_match_persona.py`,
`test/test_draft_skill.py`, `test/test_rbac_leakage.py`, and
`test/graphdb_comparison.py`. All seven now run in CI on every relevant PR.
