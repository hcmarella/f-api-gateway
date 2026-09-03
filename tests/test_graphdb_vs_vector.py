"""TC-2.x — GraphDB (Neo4j) vs. pgvector retrieval test cases.

Requires docker-compose.test.yml's neo4j-test service running:
    docker compose -f docker-compose.yml -f docker-compose.test.yml up -d neo4j-test
The whole module is skipped if it's unreachable.

Uses TEAM_B ('host') — the team this build designates for the GraphDB test
lane (see tests/fixtures/golden_questions.py and Step 10 of the original
build, test/graphdb_comparison.py).
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
import pytest
from pgvector.psycopg import register_vector

from app.config import settings
from app.ingestion.local_md_ingest import chunk_text
from app.ingestion.local_md_ingest import ingest as ingest_pgvector
from app.rag.embed import embed_query, embed_texts

from tests.fixtures.golden_questions import MULTI_HOP_QUESTION, SINGLE_HOP_QUESTION, TEAM_B

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j-test:7687")
NEO4J_AUTH = ("neo4j", "testpassword123")
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "docs"


def _neo4j_available() -> bool:
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH, connection_timeout=3)
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _neo4j_available(),
    reason=f"neo4j-test not reachable at {NEO4J_URI} — start it with "
    "'docker compose -f docker-compose.yml -f docker-compose.test.yml up -d neo4j-test'",
)


def _ingest_neo4j(team_id: str):
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with driver.session() as session:
        session.run(
            "CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
        )
        session.run("MATCH (c:Chunk {team_id: $team_id}) DETACH DELETE c", team_id=team_id)
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            chunks = chunk_text(text)
            embeddings = embed_texts(chunks)
            for i, (content, embedding) in enumerate(zip(chunks, embeddings)):
                session.run(
                    "CREATE (c:Chunk {chunk_id: $chunk_id, team_id: $team_id, source_ref: $source_ref, "
                    "content: $content, embedding: $embedding})",
                    chunk_id=f"neo4j-{path.stem}-{i}", team_id=team_id, source_ref=path.name,
                    content=content, embedding=embedding,
                )
    driver.close()


def _query_neo4j(question: str, team_id: str, top_k: int = 3):
    from neo4j import GraphDatabase
    query_embedding = embed_query(question)
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    start = time.time()
    with driver.session() as session:
        result = session.run(
            "CALL db.index.vector.queryNodes('chunk_embeddings', $k, $embedding) "
            "YIELD node, score WHERE node.team_id = $team_id "
            "RETURN node.chunk_id AS chunk_id, node.source_ref AS source_ref, score "
            "ORDER BY score DESC LIMIT $k",
            k=top_k, embedding=query_embedding, team_id=team_id,
        )
        # Lucene rescales cosine similarity to [0,1] via (cos_sim+1)/2 — convert back
        # so this is directly comparable to pgvector's raw cosine similarity.
        rows = [{"chunk_id": r["chunk_id"], "source_ref": r["source_ref"], "score": 2 * r["score"] - 1} for r in result]
    latency_ms = (time.time() - start) * 1000
    driver.close()
    return rows, latency_ms


def _query_pgvector(question: str, team_id: str, top_k: int = 3):
    query_embedding = embed_query(question)
    start = time.time()
    with psycopg.connect(settings.postgres_dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT kc.chunk_id, d.source_ref, 1 - (kc.embedding <=> %s::vector) AS score "
                "FROM knowledge_chunks kc JOIN documents d ON d.document_id = kc.document_id "
                "WHERE kc.team_id = %s ORDER BY kc.embedding <=> %s::vector LIMIT %s",
                (query_embedding, team_id, query_embedding, top_k),
            )
            rows = [{"chunk_id": r[0], "source_ref": r[1], "score": float(r[2])} for r in cur.fetchall()]
    latency_ms = (time.time() - start) * 1000
    return rows, latency_ms


def _log_eval_case(question, engine, confidence, latency_ms, passed, details):
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO eval_case_log (team_id, question, retrieval_engine, confidence, latency_ms, passed, details) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (TEAM_B, question, engine, confidence, latency_ms, passed, json.dumps(details)),
            )
        conn.commit()


@pytest.fixture(scope="module", autouse=True)
def seeded_both_engines():
    ingest_pgvector(KNOWLEDGE_DIR, TEAM_B)
    _ingest_neo4j(TEAM_B)


def test_tc2_1_single_hop_pgvector_at_least_comparable():
    """Single-hop, direct lookup: pgvector should win or tie — both engines
    here do the SAME vector search (Neo4j's is not doing graph traversal),
    so 'tie' is the expected and correct outcome, not a surprise."""
    pg_rows, pg_latency = _query_pgvector(SINGLE_HOP_QUESTION, TEAM_B)
    neo_rows, neo_latency = _query_neo4j(SINGLE_HOP_QUESTION, TEAM_B)

    pg_score = pg_rows[0]["score"] if pg_rows else 0.0
    neo_score = neo_rows[0]["score"] if neo_rows else 0.0

    _log_eval_case(SINGLE_HOP_QUESTION, "pgvector", pg_score, pg_latency, pg_score >= 0.55, {"top": pg_rows[:1]})
    _log_eval_case(SINGLE_HOP_QUESTION, "neo4j", neo_score, neo_latency, neo_score >= 0.55, {"top": neo_rows[:1]})

    print(f"\npgvector: score={pg_score:.4f} latency={pg_latency:.1f}ms")
    print(f"neo4j:    score={neo_score:.4f} latency={neo_latency:.1f}ms")

    # Same embeddings, same math — allow float/Lucene-quantization noise,
    # not a strict pgvector > neo4j assertion (that would be testing noise).
    assert abs(pg_score - neo_score) < 0.02, (
        f"scores diverged more than expected for identical embeddings: pgvector={pg_score:.4f} neo4j={neo_score:.4f}"
    )
    assert pg_score >= 0.55, f"pgvector didn't confidently match an easy single-hop question: {pg_score:.4f}"


def test_tc2_2_multi_hop_reveals_confidence_without_correctness():
    """The REAL finding this test case surfaces, run for real: pgvector's
    top match for this multi-hop question is deployment-runbook.md at 0.568
    — ABOVE this build's 0.55 'confident' threshold — purely on surface
    vocabulary overlap ('deployment pipeline', 'publishes'). That document
    contains zero information about application dependencies or team
    ownership, which is what the question actually asks. Neo4j agrees
    (0.568) because it's running the identical vector search — no entity
    relationships (pipeline -> service -> application -> team) were ever
    modeled in either engine, so neither can do real multi-hop reasoning.
    This is a genuine confidence/correctness gap for compound questions,
    not a graph-vs-vector question at all — proof the graph was never
    built, and proof this build's confidence score doesn't know the
    difference between 'topically related' and 'actually answers this'."""
    pg_rows, pg_latency = _query_pgvector(MULTI_HOP_QUESTION, TEAM_B)
    neo_rows, neo_latency = _query_neo4j(MULTI_HOP_QUESTION, TEAM_B)

    pg_top = pg_rows[0] if pg_rows else None
    neo_top = neo_rows[0] if neo_rows else None
    pg_score = pg_top["score"] if pg_top else 0.0
    neo_score = neo_top["score"] if neo_top else 0.0

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM knowledge_chunks WHERE chunk_id = %s", (pg_top["chunk_id"],))
            pg_top_content = cur.fetchone()[0]

    _log_eval_case(MULTI_HOP_QUESTION, "pgvector", pg_score, pg_latency, False, {"note": "confident but non-answering top match", "top_source": pg_top["source_ref"]})
    _log_eval_case(MULTI_HOP_QUESTION, "neo4j", neo_score, neo_latency, False, {"note": "confident but non-answering top match", "top_source": neo_top["source_ref"]})

    print(f"\nMulti-hop question: {MULTI_HOP_QUESTION!r}")
    print(f"pgvector top match: {pg_top['source_ref']} score={pg_score:.4f} (>= 0.55 'confident' threshold)")
    print(f"neo4j    top match: {neo_top['source_ref']} score={neo_score:.4f}")

    # The actual facts the question asks for (application names, dependency
    # edges, ownership) are absent from the top-scored document — that's
    # the real, asserted finding, not an arbitrary score cutoff.
    missing_facts = ["depends on", "owns", "owned by"]
    facts_present = [f for f in missing_facts if f in pg_top_content.lower()]
    assert facts_present == [], (
        f"top-matched document unexpectedly contains dependency/ownership language ({facts_present}) "
        f"— this specific finding may not replicate; re-verify against the current corpus"
    )
    assert pg_score >= 0.55, (
        "expected to reproduce the 'confident but wrong' finding (score >= 0.55 on a "
        "non-answering document) — if this no longer holds, the corpus or embedding model "
        "changed and this test needs new fixture content, not a lowered bar"
    )


def test_tc2_3_token_proxy_comparison():
    """Real Bedrock input/output token counts require an actual model call
    (synthesize() is mocked — see docs/BUILD_SUMMARY.md Phase 5), so this
    measures retrieved-context word count as a token proxy instead, clearly
    labeled as such rather than presented as real Bedrock usage."""
    for question in (SINGLE_HOP_QUESTION, MULTI_HOP_QUESTION):
        pg_rows, _ = _query_pgvector(question, TEAM_B)
        neo_rows, _ = _query_neo4j(question, TEAM_B)
        # Proxy only — chunk word counts, not real Claude tokenization.
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sum(token_count) FROM knowledge_chunks WHERE team_id=%s AND chunk_id = ANY(%s)",
                    (TEAM_B, [r["chunk_id"] for r in pg_rows]),
                )
                pg_proxy_tokens = cur.fetchone()[0] or 0
        print(f"\n{question!r}\n  pgvector context proxy tokens: {pg_proxy_tokens} (word-count proxy, not real Bedrock tokenization)")
    pytest.skip(
        "Real input_tokens/output_tokens/cost-per-response require an actual Bedrock call "
        "(cache_read_input_tokens etc. in the response metadata) — not measurable while "
        "synthesize() is mocked. The word-count proxy above is printed for visibility but "
        "isn't asserted on, since it isn't the real metric this test case asks for."
    )


def test_tc2_4_human_rated_recall_quality():
    pytest.skip(
        "Blind human quality rating requires distinct real answers to compare — synthesize() "
        "always returns the identical fixed mock string regardless of engine or question right "
        "now, so every 'answer' is the same text. Rating it would be meaningless until Phase 5 "
        "(real model call) lands."
    )


def test_tc2_5_neo4j_failure_falls_back_gracefully():
    """No live request path in this app actually routes to Neo4j at query
    time — docker-compose.test.yml's own header says it's test-only,
    never merged into the main stack. This tests the comparison harness's
    own resilience (bounded failure, not a hang), not a live fallback
    behavior that doesn't exist to test."""
    import shutil
    import subprocess
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable

    if shutil.which("docker") is None:
        pytest.skip(
            "'docker' CLI isn't available inside the gateway container (no docker socket "
            "mounted, by design — this app container shouldn't need to control sibling "
            "containers). Run this specific test from the host instead: "
            "'pytest tests/test_graphdb_vs_vector.py::test_tc2_5_neo4j_failure_falls_back_gracefully' "
            "with a host Python environment that has network access to neo4j-test."
        )

    subprocess.run(["docker", "stop", "f-api-gateway-neo4j-test-1"], check=True, capture_output=True)
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH, connection_timeout=3)
        with pytest.raises((ServiceUnavailable, OSError, Exception)):
            with driver.session() as session:
                session.run("RETURN 1").consume()
        driver.close()
    finally:
        subprocess.run(["docker", "start", "f-api-gateway-neo4j-test-1"], check=True, capture_output=True)
        for _ in range(30):
            if _neo4j_available():
                break
            time.sleep(2)
        else:
            pytest.fail("neo4j-test did not come back healthy after restart — left in a bad state, check manually")
