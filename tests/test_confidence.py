"""TC-3.x — confidence score test cases.

Confidence in this build == raw pgvector cosine similarity from rag_node.
There is no freshness weighting, no conflict detection, and no calibration
step beyond the empirical 0.55 threshold in app/agents/graph.py — several
test cases below exist specifically to make that visible, not to hide it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
import pytest

from app.agents.graph import rag_node, run_question
from app.agents.nodes.draft_skill import FALLBACK_ANSWER
from app.config import settings
from app.ingestion.local_md_ingest import chunk_text, make_chunk_id, upsert_chunk, upsert_document
from app.rag.embed import embed_texts

from tests.fixtures.golden_questions import TEAM_A, UNANSWERABLE_QUESTION


@pytest.mark.xfail(
    reason="Empirically, this build's confidence score (raw BGE cosine similarity for "
    "asymmetric query-to-passage retrieval) tops out around 0.75-0.80 on this corpus even for "
    "a clean single-document match — it does not reach the requested >0.85 bar. That bar holds "
    "for near-identical paraphrase pairs (see test_embed_similarity.py) but not for a real "
    "question against its answering passage. This is a genuine calibration gap, not a flaky "
    "test — see docs/BUILD_SUMMARY.md.",
    strict=True,
)
def test_tc3_1_high_confidence_clean_case():
    question = "What's our policy on data retention for conversations?"
    result = rag_node({"question": question, "team_id": TEAM_A})["rag_result"]
    print(f"\nconfidence={result['best_score']:.4f} (bar: >0.85)")
    assert result["best_score"] > 0.85


def test_tc3_2_conflicting_sources_both_surface_as_candidates(scratch_team, db_conn):
    """Two genuinely conflicting documents on the same topic should both
    appear as retrieval candidates with comparable scores — the system
    doesn't currently pick one and hide the conflict at the retrieval
    layer (whether synthesize() would surface the conflict in the answer
    text is untested below: it's mocked)."""
    doc_old = (
        "PTO Policy (2019): Employees accrue 15 days of paid time off annually. "
        "Unused days do not roll over into the next calendar year."
    )
    doc_new = (
        "PTO Policy (2025): The company offers unlimited paid time off for all "
        "full-time employees, subject to manager approval for extended leave."
    )

    for i, (label, text) in enumerate([("old", doc_old), ("new", doc_new)]):
        source_ref = f"tc3-2-{label}"
        document_id = upsert_document(db_conn, scratch_team, source_ref, f"PTO policy ({label})", "n/a")
        chunks = chunk_text(text)
        embeddings = embed_texts(chunks)
        chunk_id = make_chunk_id(scratch_team, source_ref, 0)
        upsert_chunk(db_conn, chunk_id, scratch_team, document_id, chunks[0], embeddings[0], 0, len(chunks[0].split()))
    db_conn.commit()

    result = rag_node({"question": "What is our vacation/PTO policy?", "team_id": scratch_team})["rag_result"]
    print(f"\ncandidates: {[(c['chunk_id'], round(c['similarity'], 4)) for c in result['chunks']]}")

    assert len(result["chunks"]) >= 2, "expected both conflicting documents to surface as candidates"
    top_two_scores = sorted((c["similarity"] for c in result["chunks"]), reverse=True)[:2]
    assert (top_two_scores[0] - top_two_scores[1]) < 0.15, (
        "the two conflicting sources scored too far apart to both be considered — "
        "one would silently dominate"
    )


def test_tc3_2_note_conflict_surfacing_not_testable():
    pytest.skip(
        "synthesize() is mocked — there is no real answer text to check for an explicit "
        "'sources disagree' warning. The retrieval-layer claim (both candidates surface) is "
        "covered above."
    )


@pytest.mark.xfail(
    reason="No freshness weighting exists anywhere in the confidence formula — rag_node's "
    "score is pure cosine similarity, with zero reference to documents.updated_at. This is a "
    "real, currently-unimplemented gap (ARCHITECTURE.md's Freshness gate), not a bug in this "
    "test.",
    strict=True,
)
def test_tc3_3_stale_source_confidence_penalty(scratch_team, db_conn):
    text = "The deployment pipeline runs on Jenkins and deploys every commit to main automatically."
    source_ref = "tc3-3-stale"
    document_id = upsert_document(db_conn, scratch_team, source_ref, "Stale doc", "n/a")
    chunks = chunk_text(text)
    embeddings = embed_texts(chunks)
    chunk_id = make_chunk_id(scratch_team, source_ref, 0)
    upsert_chunk(db_conn, chunk_id, scratch_team, document_id, chunks[0], embeddings[0], 0, len(chunks[0].split()))
    with db_conn.cursor() as cur:
        cur.execute("UPDATE documents SET updated_at = now() - interval '400 days' WHERE document_id = %s", (document_id,))
    db_conn.commit()

    fresh_score_reference = rag_node({"question": "How does the deployment pipeline work?", "team_id": scratch_team})["rag_result"]["best_score"]

    # There's nothing to compare against — a "fresh" twin of this doc doesn't
    # exist, so the real assertion is simply: does the score reflect the
    # 400-day-old updated_at at all? It never does, by construction of the
    # current formula.
    with db_conn.cursor() as cur:
        cur.execute("SELECT updated_at FROM documents WHERE document_id = %s", (document_id,))
        updated_at = cur.fetchone()[0]

    print(f"\ndocument updated_at={updated_at}, confidence={fresh_score_reference:.4f} — no penalty applied")
    assert False, "no freshness penalty logic exists to assert against — confidence is pure cosine similarity"


def test_tc3_4_zero_match_says_unverified():
    result = run_question(UNANSWERABLE_QUESTION, team_id=TEAM_A, persona="business")
    print(f"\nanswer={result['answer']!r}")
    assert result["answer"] == FALLBACK_ANSWER
    assert "skill_gap_log_id" in result, "expected draft_skill to fire for a genuinely unanswerable question"

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            # skill_gap_log.review_queue_id FKs to content_review_queue — delete child first.
            cur.execute("DELETE FROM skill_gap_log WHERE id = %s", (result["skill_gap_log_id"],))
            cur.execute("DELETE FROM content_review_queue WHERE id = %s", (result["review_queue_id"],))
        conn.commit()


def test_tc3_5_confidence_to_outcome_correlation():
    pytest.skip(
        "Requires a manual_ratings table (doesn't exist) and eval_case_log data collected "
        "over time (a 'nightly, for a week' cadence) — no scheduled eval job exists in this "
        "build. Not fabricable as a one-shot test; needs the longitudinal infrastructure built "
        "first."
    )
