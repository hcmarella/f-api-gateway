"""Confirms draft_skill fires when triage+skill_match+rag_node all fail to
confidently match, logs skill_gap_log + content_review_queue rows, and never
writes to knowledge/skills/. Run: python test/test_draft_skill.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from app.agents.graph import run_question
from app.config import settings

QUESTION = "Can you recommend a good recipe for banana bread?"


def main():
    skills_dir = Path(__file__).resolve().parent.parent / "knowledge" / "skills"
    files_before = set(skills_dir.rglob("*.md"))

    result = run_question(QUESTION, team_id="test", persona="business")

    print(f"route={result['route']}")
    print(f"skill_result={result['skill_result']}")
    print(f"rag_result.matched={result['rag_result']['matched']} best_score={result['rag_result']['best_score']:.4f}")
    print(f"answer={result['answer']!r}")
    print(f"skill_gap_log_id={result.get('skill_gap_log_id')}")
    print(f"review_queue_id={result.get('review_queue_id')}")

    assert "skill_gap_log_id" in result, "draft_skill did not fire — expected all branches to fail for this question"

    files_after = set(skills_dir.rglob("*.md"))
    assert files_before == files_after, "draft_skill wrote directly to knowledge/skills/ — it must never do this"
    print("\n[PASS] no files written to knowledge/skills/")

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, team_id, question, review_queue_id FROM skill_gap_log WHERE id = %s",
                (result["skill_gap_log_id"],),
            )
            gap_row = cur.fetchone()
            print(f"\nskill_gap_log row: {gap_row}")

            cur.execute(
                "SELECT id, team_id, target, status, proposed_content FROM content_review_queue WHERE id = %s",
                (result["review_queue_id"],),
            )
            queue_row = cur.fetchone()
            print(f"\ncontent_review_queue row: id={queue_row[0]} team_id={queue_row[1]} target={queue_row[2]} status={queue_row[3]}")
            print(f"proposed_content:\n{queue_row[4]}")

    assert gap_row is not None, "skill_gap_log row missing"
    assert queue_row is not None, "content_review_queue row missing"
    assert queue_row[2] == "new_skill"
    assert queue_row[3] == "pending"
    print("\n[PASS] both rows exist with expected target/status")


if __name__ == "__main__":
    main()
