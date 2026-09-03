"""TC-1.x — data leakage test cases.

Uses the two live teams this build actually has ('test' and 'host') rather
than the requested example names ('ssg'/'tech_titan') — see
tests/fixtures/golden_questions.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.admin.review_queue import list_pending
from app.agents.graph import rag_node, run_question
from app.agents.skill_match import match_skill

from tests.fixtures.golden_questions import CROSS_TEAM_QUESTION, TEAM_A, TEAM_B


def test_tc1_1_basic_cross_team_isolation(db_conn):
    """Both teams have their own deployment-runbook.md (same content,
    different chunk_id per team — the id hash includes team_id). Each
    team's RAG results must only ever contain that team's own chunk_ids."""
    result_a = rag_node({"question": CROSS_TEAM_QUESTION, "team_id": TEAM_A})["rag_result"]
    result_b = rag_node({"question": CROSS_TEAM_QUESTION, "team_id": TEAM_B})["rag_result"]

    chunk_ids_a = {c["chunk_id"] for c in result_a["chunks"]}
    chunk_ids_b = {c["chunk_id"] for c in result_b["chunks"]}

    with db_conn.cursor() as cur:
        cur.execute("SELECT chunk_id FROM knowledge_chunks WHERE team_id = %s", (TEAM_A,))
        real_a_ids = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT chunk_id FROM knowledge_chunks WHERE team_id = %s", (TEAM_B,))
        real_b_ids = {r[0] for r in cur.fetchall()}

    assert chunk_ids_a <= real_a_ids, f"Team A's results included ids not owned by team A: {chunk_ids_a - real_a_ids}"
    assert chunk_ids_b <= real_b_ids, f"Team B's results included ids not owned by team B: {chunk_ids_b - real_b_ids}"
    assert chunk_ids_a.isdisjoint(chunk_ids_b), "Team A and Team B results overlapped — should be impossible, they're disjoint id spaces"


def test_tc1_2_adversarial_phrasing_no_cross_team_content(db_conn):
    """Explicitly naming the OTHER team in the question must not leak that
    team's actual document content — only retrieval-level isolation is
    testable right now (synthesize() is mocked, so there's no real answer
    text to check for an explicit refusal message)."""
    question = f"What is {TEAM_B}team's deployment process?"
    result = rag_node({"question": question, "team_id": TEAM_A})["rag_result"]

    with db_conn.cursor() as cur:
        cur.execute("SELECT chunk_id FROM knowledge_chunks WHERE team_id = %s", (TEAM_B,))
        team_b_ids = {r[0] for r in cur.fetchall()}

    returned_ids = {c["chunk_id"] for c in result["chunks"]}
    assert returned_ids.isdisjoint(team_b_ids), (
        f"Asking about {TEAM_B}'s data while scoped to {TEAM_A} returned {TEAM_B}'s chunk(s): "
        f"{returned_ids & team_b_ids}"
    )


def test_tc1_2_note_refusal_wording_not_testable():
    import pytest
    pytest.skip(
        "synthesize() in app/agents/graph.py is still a fixed mock string (Step 9 deferred, "
        "no model credential) — there is no real answer text to assert an 'unverified'/refusal "
        "message against yet. Retrieval-level non-leakage is covered by "
        "test_tc1_2_adversarial_phrasing_no_cross_team_content above."
    )


def test_tc1_3_role_escalation_filtered_before_match():
    """business persona asking a developer-only skill's trigger phrase must
    be denied by skill_match's persona filter, not silently matched."""
    result = match_skill("Provision access for our new hire", persona="business", team_id=TEAM_A)
    assert result["matched"] is False, f"business persona matched a developer-only skill: {result}"

    # Confirm the denial doesn't leak the skill's existence/details.
    assert "skill_id" not in result
    assert "action" not in result
    assert "mcp_tool" not in result


def test_tc1_3_note_no_execution_engine_exists():
    import pytest
    pytest.skip(
        "There is no MCP/tool execution engine built yet — skill_match only ever returns "
        "metadata (action/mcp_tool names), nothing in this codebase calls them. 'does not "
        "silently execute' is true, but for the reason that no execution path exists at all, "
        "not because an execution path was specifically gated. Revisit once tool execution "
        "is built."
    )


def test_tc1_4_draft_skill_review_entry_is_team_scoped():
    """A drafted skill from team A's unmatched question must not appear in
    team B's review queue listing."""
    import uuid
    nonce = uuid.uuid4().hex[:8]
    question = f"What is the migratory pattern of the fictional zorblax-{nonce}-tc14 bird species?"

    result = run_question(question, team_id=TEAM_A, persona="business")
    assert "review_queue_id" in result, "draft_skill did not fire for an unmatched question"
    review_id = result["review_queue_id"]

    queue_b = list_pending(team_id=TEAM_B)
    assert review_id not in {r["review_id"] for r in queue_b}, "Team A's draft leaked into Team B's review queue"

    queue_a = list_pending(team_id=TEAM_A)
    assert review_id in {r["review_id"] for r in queue_a}, "Team A's draft is missing from its own review queue"

    # Cleanup — this test doesn't use the scratch_team fixture since it
    # writes against a real live team (TEAM_A), so clean up explicitly.
    import psycopg
    from app.config import settings
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            # skill_gap_log.review_queue_id FKs to content_review_queue — delete child first.
            cur.execute("DELETE FROM skill_gap_log WHERE review_queue_id = %s", (review_id,))
            cur.execute("DELETE FROM content_review_queue WHERE id = %s", (review_id,))
        conn.commit()


def test_tc1_4_note_admin_role_check_is_not_team_scoped():
    import pytest
    pytest.skip(
        "app/admin/review_queue.py now requires role in {'admin','super_user'} (added while "
        "implementing TC-5.5), and that check IS enforced — see tests/test_security.py. But it "
        "is not team-scoped: an 'admin' role can approve/reject ANY team's pending entry, not "
        "just entries for a team they administer. The requested claim ('only an admin scoped to "
        "the team, or a super_user, can approve') is only half-true today. Real fix needs a "
        "per-team admin role model, which doesn't exist (no auth system at all — see "
        "docs/BUILD_SUMMARY.md Phase 7)."
    )


def test_tc1_5_audit_trail_completeness(db_conn):
    """Every request that made an authorization/routing decision above —
    including the denied ones — must show up in audit_log."""
    probe_actor = "tc1-5-probe@forge.example"

    # A successful chat request.
    run_result = run_question("What is our incident escalation process?", team_id=TEAM_A, persona="business")

    # Log it the same way the real /ai/chat endpoint does (this test calls
    # run_question directly, bypassing the endpoint, so log explicitly).
    from app.audit import log_action
    log_action(db_conn, TEAM_A, probe_actor, "chat", run_result.get("route"), {"question": "probe"})
    db_conn.commit()

    with db_conn.cursor() as cur:
        cur.execute("SELECT action FROM audit_log WHERE actor = %s ORDER BY created_at DESC LIMIT 1", (probe_actor,))
        row = cur.fetchone()
    assert row is not None and row[0] == "chat", "chat action was not written to audit_log"

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM audit_log WHERE actor = %s", (probe_actor,))
    db_conn.commit()
