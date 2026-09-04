"""TC-3.x — confidence score test cases.

Confidence in this build == pgvector cosine similarity from rag_node,
adjusted by a real freshness penalty (source_updated_at, see
_freshness_factor in app/agents/graph.py). There is still no conflict
detection, and no calibration step beyond the empirical 0.55 threshold —
those test cases exist specifically to make the remaining gaps visible,
not to hide them.
"""

import sys
from datetime import datetime, timedelta, timezone
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


def test_tc3_3_stale_source_confidence_penalty(scratch_team, db_conn):
    """knowledge_chunks.source_updated_at (db/migrations/V2__memory_model.sql)
    now feeds a real freshness penalty in rag_node (app/agents/graph.py:
    _freshness_factor) — this closes what used to be a documented,
    xfail'd gap. Proven with a controlled pair: identical content, only
    source_updated_at differs, so any score difference is attributable to
    freshness alone, not to a coincidentally-better semantic match."""
    text = "The deployment pipeline runs on Jenkins and deploys every commit to main automatically."

    fresh_ref = "tc3-3-fresh"
    fresh_doc_id = upsert_document(db_conn, scratch_team, fresh_ref, "Fresh twin", "n/a")
    stale_ref = "tc3-3-stale"
    stale_doc_id = upsert_document(db_conn, scratch_team, stale_ref, "Stale twin", "n/a")

    chunks = chunk_text(text)
    embeddings = embed_texts(chunks)

    fresh_chunk_id = make_chunk_id(scratch_team, fresh_ref, 0)
    upsert_chunk(
        db_conn, fresh_chunk_id, scratch_team, fresh_doc_id, chunks[0], embeddings[0], 0, len(chunks[0].split()),
        source_updated_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    stale_chunk_id = make_chunk_id(scratch_team, stale_ref, 0)
    upsert_chunk(
        db_conn, stale_chunk_id, scratch_team, stale_doc_id, chunks[0], embeddings[0], 0, len(chunks[0].split()),
        source_updated_at=datetime.now(timezone.utc) - timedelta(days=400),
    )
    db_conn.commit()

    result = rag_node({"question": "How does the deployment pipeline work?", "team_id": scratch_team})["rag_result"]
    by_id = {c["chunk_id"]: c for c in result["chunks"]}
    fresh_c, stale_c = by_id[fresh_chunk_id], by_id[stale_chunk_id]

    print(f"\nfresh: raw={fresh_c['raw_similarity']:.4f} adjusted={fresh_c['similarity']:.4f} freshness={fresh_c['freshness_factor']:.4f}")
    print(f"stale: raw={stale_c['raw_similarity']:.4f} adjusted={stale_c['similarity']:.4f} freshness={stale_c['freshness_factor']:.4f}")

    assert fresh_c["raw_similarity"] == pytest.approx(stale_c["raw_similarity"], abs=1e-6), (
        "identical content should embed identically — raw similarity should match; "
        "if it doesn't, this test's premise (isolating freshness as the only variable) is broken"
    )
    assert fresh_c["freshness_factor"] == 1.0, "10-day-old content is within the grace period, should have zero penalty"
    assert stale_c["freshness_factor"] < 1.0, "400-day-old content should have a real freshness penalty applied"
    assert stale_c["similarity"] < fresh_c["similarity"], (
        "stale content scored the same as or higher than its identical fresh twin — "
        "the freshness penalty isn't actually affecting ranking"
    )


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
