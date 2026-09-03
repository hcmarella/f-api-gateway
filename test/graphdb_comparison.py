"""Compares pgvector vs. Neo4j vector index retrieval on the same corpus and
golden question set, logging every result to eval_case_log.

Requires docker-compose.test.yml's neo4j-test service running:
    docker compose -f docker-compose.yml -f docker-compose.test.yml up -d neo4j-test

Run: python test/graphdb_comparison.py
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from neo4j import GraphDatabase
from pgvector.psycopg import register_vector

from app.config import settings
from app.ingestion.local_md_ingest import chunk_text
from app.ingestion.local_md_ingest import ingest as ingest_pgvector
from app.rag.embed import embed_query, embed_texts

TEAM_ID = "host"
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "docs"
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j-test:7687")
NEO4J_AUTH = ("neo4j", "testpassword123")
TOP_K = 3
PASS_SCORE_THRESHOLD = 0.55

# (question, expected source filename that should be the top match)
GOLDEN_QUESTIONS = [
    ("What's our policy on data retention for conversations?", "data-retention.md"),
    ("How long does the reset link stay valid for password resets?", "password-reset.md"),
    ("What severity level requires paging on-call immediately?", "incident-response.md"),
    ("How do I rotate an API key?", "api-authentication.md"),
    ("What happens if we exceed our plan's included volume?", "billing-faq.md"),
    ("How does SSO configuration work for a new customer team?", "sso-setup.md"),
    ("What's the default rate limit per team?", "rate-limits.md"),
    ("What should I do in my first week as a new engineer?", "onboarding-new-engineers.md"),
]


def ingest_neo4j(knowledge_dir: Path, team_id: str):
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    with driver.session() as session:
        session.run(
            """
            CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
            FOR (c:Chunk) ON (c.embedding)
            OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}
            """
        )
        session.run("MATCH (c:Chunk {team_id: $team_id}) DETACH DELETE c", team_id=team_id)

        md_files = sorted(knowledge_dir.glob("*.md"))
        total_chunks = 0
        for path in md_files:
            text = path.read_text(encoding="utf-8")
            # Use the identical chunking as the pgvector ingestion path so
            # both engines embed the same text — otherwise the comparison
            # isn't apples-to-apples.
            chunks = chunk_text(text)
            embeddings = embed_texts(chunks)
            for i, (chunk_content, embedding) in enumerate(zip(chunks, embeddings)):
                session.run(
                    """
                    CREATE (c:Chunk {
                        chunk_id: $chunk_id, team_id: $team_id, source_ref: $source_ref,
                        content: $content, embedding: $embedding
                    })
                    """,
                    chunk_id=f"neo4j-{path.stem}-{i}",
                    team_id=team_id,
                    source_ref=path.name,
                    content=chunk_content,
                    embedding=embedding,
                )
                total_chunks += 1
        print(f"Neo4j: ingested {total_chunks} chunks for team_id='{team_id}'")
    driver.close()


def query_neo4j(question: str, team_id: str, top_k: int = TOP_K):
    query_embedding = embed_query(question)
    driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    start = time.time()
    with driver.session() as session:
        result = session.run(
            """
            CALL db.index.vector.queryNodes('chunk_embeddings', $k, $embedding)
            YIELD node, score
            WHERE node.team_id = $team_id
            RETURN node.chunk_id AS chunk_id, node.source_ref AS source_ref, score
            ORDER BY score DESC
            LIMIT $k
            """,
            k=top_k,
            embedding=query_embedding,
            team_id=team_id,
        )
        # Neo4j's vector index (backed by Lucene) returns cosine similarity
        # rescaled to [0,1] via (cos_sim + 1) / 2, not raw cosine similarity.
        # Convert back so this is directly comparable to pgvector's raw
        # cosine similarity — otherwise Neo4j looks artificially "more
        # confident" for no retrieval-quality reason.
        rows = [{"chunk_id": r["chunk_id"], "source_ref": r["source_ref"], "score": 2 * r["score"] - 1} for r in result]
    latency_ms = (time.time() - start) * 1000
    driver.close()
    return rows, latency_ms


def query_pgvector(question: str, team_id: str, top_k: int = TOP_K):
    query_embedding = embed_query(question)
    start = time.time()
    with psycopg.connect(settings.postgres_dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kc.chunk_id, d.source_ref, 1 - (kc.embedding <=> %s::vector) AS score
                FROM knowledge_chunks kc
                JOIN documents d ON d.document_id = kc.document_id
                WHERE kc.team_id = %s
                ORDER BY kc.embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, team_id, query_embedding, top_k),
            )
            rows = [{"chunk_id": r[0], "source_ref": r[1], "score": float(r[2])} for r in cur.fetchall()]
    latency_ms = (time.time() - start) * 1000
    return rows, latency_ms


def log_eval_case(conn, team_id, question, engine, confidence, latency_ms, passed, details):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO eval_case_log (team_id, question, retrieval_engine, confidence, latency_ms, passed, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (team_id, question, engine, confidence, latency_ms, passed, json.dumps(details)),
        )
    conn.commit()


def run_comparison():
    print(f"=== Ingesting corpus into both engines for team_id='{TEAM_ID}' ===")
    ingest_pgvector(KNOWLEDGE_DIR, TEAM_ID)
    ingest_neo4j(KNOWLEDGE_DIR, TEAM_ID)

    print(f"\n=== Running {len(GOLDEN_QUESTIONS)} golden questions against both engines ===")
    results = {"pgvector": [], "neo4j": []}

    with psycopg.connect(settings.postgres_dsn) as conn:
        for question, expected_source in GOLDEN_QUESTIONS:
            for engine, query_fn in [("pgvector", query_pgvector), ("neo4j", query_neo4j)]:
                rows, latency_ms = query_fn(question, TEAM_ID)
                top = rows[0] if rows else None
                confidence = top["score"] if top else 0.0
                # expected_source is a base filename; pgvector's source_ref is
                # "knowledge/docs/<file>.md", neo4j's is just "<file>.md".
                matched_expected = bool(top) and top["source_ref"].endswith(expected_source)
                passed = matched_expected and confidence >= PASS_SCORE_THRESHOLD

                results[engine].append({"question": question, "confidence": confidence, "latency_ms": latency_ms, "passed": passed})

                log_eval_case(
                    conn, TEAM_ID, question, engine, confidence, latency_ms, passed,
                    {"expected_source": expected_source, "top_result": top, "all_results": rows},
                )
                print(f"  [{engine:8s}] {'PASS' if passed else 'FAIL'}  score={confidence:.4f}  latency={latency_ms:6.1f}ms  {question!r}")

    print("\n=== Summary ===")
    for engine in ("pgvector", "neo4j"):
        rows = results[engine]
        avg_conf = sum(r["confidence"] for r in rows) / len(rows)
        avg_latency = sum(r["latency_ms"] for r in rows) / len(rows)
        pass_rate = sum(1 for r in rows if r["passed"]) / len(rows)
        print(f"{engine:10s}  avg_confidence={avg_conf:.4f}  avg_latency_ms={avg_latency:7.2f}  pass_rate={pass_rate:.0%}  (n={len(rows)})")


if __name__ == "__main__":
    run_comparison()
