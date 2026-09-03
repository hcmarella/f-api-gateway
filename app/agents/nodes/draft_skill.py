"""draft_skill node.

Fires only when triage + skill_match + rag_node all fail to confidently
match a question. Logs the gap to skill_gap_log, drafts a proposed skill via
a (mocked, for now) Claude call, and stages it in content_review_queue with
status='pending', target='new_skill'. This node NEVER writes to
knowledge/skills/ directly — that only happens through the human-reviewed
approve endpoint (see app/admin/review_queue.py). It always returns a
graceful fallback answer rather than pretending to have a real one.
"""

import json
import re

import psycopg
import yaml

from app.config import settings

FALLBACK_ANSWER = (
    "I don't have a confident answer or an existing skill for that yet. "
    "I've logged this as a knowledge gap and drafted a proposed skill for "
    "a reviewer to look at — in the meantime, you may want to check with "
    "a teammate or file a ticket."
)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:50] or "untitled-skill"


def mock_claude_draft_skill(question: str, persona: str, team_id: str) -> str:
    """Stand-in for a real Claude API call that would draft a proposed skill
    file from the unmatched question. Replace the body of this function with
    an actual model call later; the calling code doesn't need to change."""
    skill_id = _slugify(question)
    trigger = question.strip().rstrip("?.!").lower()

    frontmatter = {
        "id": skill_id,
        "name": question.strip().rstrip("?.!").title(),
        "description": f"Drafted from an unmatched question: {question.strip()}",
        "persona_access": [persona],
        "team_id": team_id,
        "triggers": [trigger],
        "action": f"TODO_{skill_id.replace('-', '_')}",
        "mcp_tool": "TODO",
        "required_permissions": [],
    }

    frontmatter_yaml = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    body = (
        f"# {frontmatter['name']}\n\n"
        f"DRAFT — auto-generated from an unmatched question, needs human review "
        f"before this becomes a real skill.\n\nOriginal question: {question.strip()}\n"
    )
    return f"---\n{frontmatter_yaml}---\n\n{body}"


def draft_skill_node(state: dict) -> dict:
    question = state["question"]
    team_id = state.get("team_id", "test")
    persona = state.get("persona", "business")

    triage_result = {
        "route": state.get("route"),
        "route_confidence": state.get("route_confidence"),
        "skill_result": state.get("skill_result"),
        "rag_result": state.get("rag_result"),
    }

    draft_content = mock_claude_draft_skill(question, persona, team_id)

    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO content_review_queue (team_id, target, proposed_content, context, status)
                VALUES (%s, 'new_skill', %s, %s, 'pending')
                RETURNING id
                """,
                (team_id, draft_content, json.dumps({"question": question, "persona": persona})),
            )
            review_queue_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO skill_gap_log (team_id, question, triage_result, review_queue_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (team_id, question, json.dumps(triage_result), review_queue_id),
            )
            skill_gap_log_id = cur.fetchone()[0]
        conn.commit()

    return {
        "answer": FALLBACK_ANSWER,
        "sources": [],
        "skill_gap_log_id": str(skill_gap_log_id),
        "review_queue_id": str(review_queue_id),
    }
