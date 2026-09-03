"""TC-4.x — token savings test cases.

TC-4.1 (prompt caching) needs a real Bedrock call and is skipped —
synthesize() is mocked (docs/BUILD_SUMMARY.md Phase 5). TC-4.2 and TC-4.3
measure real, code-driven proxies: retrieved-chunk word counts as a token
proxy, and the actual difference in what context each routing branch needs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.agents.graph import rag_node, run_question

from tests.fixtures.golden_questions import GOLDEN_QUESTIONS, TEAM_A


def test_tc4_1_prompt_caching_impact():
    pytest.skip(
        "Requires real Bedrock calls and reading cache_read_input_tokens from response "
        "metadata — synthesize() is a fixed mock string, there is no real model call to "
        "measure caching against. See docs/BUILD_SUMMARY.md Phase 5 (deferred, no credential)."
    )


def test_tc4_2_top3_vs_top10_rerank_token_tradeoff():
    """Compares current top-3 retrieval against a wider top-10 candidate
    pool trimmed back to the same top-3 by score — the point isn't token
    count alone (both call rag_node with a fixed limit), it's whether a
    wider initial candidate pool would have changed which chunk wins."""
    total_top3_tokens = 0
    total_top10_first3_tokens = 0
    disagreements = []

    for question, expected_source in GOLDEN_QUESTIONS:
        top3 = rag_node({"question": question, "team_id": TEAM_A})["rag_result"]["chunks"]

        from app.rag.embed import embed_query
        import psycopg
        from pgvector.psycopg import register_vector
        from app.config import settings

        query_embedding = embed_query(question)
        with psycopg.connect(settings.postgres_dsn) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT chunk_id, content, 1 - (embedding <=> %s::vector) AS score "
                    "FROM knowledge_chunks WHERE team_id = %s "
                    "ORDER BY embedding <=> %s::vector LIMIT 10",
                    (query_embedding, TEAM_A, query_embedding),
                )
                top10 = [{"chunk_id": r[0], "content": r[1], "similarity": float(r[2])} for r in cur.fetchall()]

        top3_ids = [c["chunk_id"] for c in top3]
        top10_first3_ids = [c["chunk_id"] for c in top10[:3]]
        if top3_ids != top10_first3_ids:
            disagreements.append((question, top3_ids, top10_first3_ids))

        total_top3_tokens += sum(len(c["content"].split()) for c in top3)
        total_top10_first3_tokens += sum(len(c["content"].split()) for c in top10[:3])

    print(f"\ntotal proxy tokens — top-3 direct: {total_top3_tokens}, top-10-then-first-3: {total_top10_first3_tokens}")
    print(f"disagreements between the two selections: {len(disagreements)}/{len(GOLDEN_QUESTIONS)}")

    # At k=3 both queries return the same top-3 by construction (LIMIT 3 vs
    # LIMIT 10 sorted the same way) — the real, honest finding is that a
    # wider candidate pool doesn't change anything without an actual
    # reranker in between. Assert that expectation explicitly.
    assert total_top3_tokens == total_top10_first3_tokens, "unexpected: same corpus/query returned different top-3 by different LIMITs"
    assert len(disagreements) == 0, (
        "a wider candidate pool changed the top-3 without a reranker in between — "
        "that shouldn't be possible with a plain ORDER BY ... LIMIT n"
    )


def test_tc4_3_skill_match_route_needs_zero_rag_tokens():
    """The whole point of correct routing: a skill_match hit needs no
    retrieval context at all, vs. a rag_node hit which needs the full
    retrieved chunk content as context. Quantify the actual difference
    using this build's own routing behavior."""
    skill_result = run_question("Create a follow-up Jira ticket for this bug", team_id=TEAM_A, persona="business")
    assert skill_result["route"] == "skill_match"
    assert skill_result.get("rag_result") is None, "skill_match route should never have touched rag_node"
    skill_route_context_tokens = 0  # no chunks retrieved for this route at all

    rag_result = run_question("What's our policy on data retention for conversations?", team_id=TEAM_A, persona="business")
    assert rag_result["route"] == "rag_node"
    rag_chunks = rag_node({"question": "What's our policy on data retention for conversations?", "team_id": TEAM_A})["rag_result"]["chunks"]
    rag_route_context_tokens = sum(len(c["content"].split()) for c in rag_chunks)

    print(f"\nskill_match route context proxy tokens: {skill_route_context_tokens}")
    print(f"rag_node route context proxy tokens: {rag_route_context_tokens}")

    assert skill_route_context_tokens == 0
    assert rag_route_context_tokens > 0, "expected the RAG route to actually need retrieved content as context"
