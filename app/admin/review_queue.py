"""Admin endpoints for approving or rejecting content_review_queue entries.

Approving a 'new_skill' entry is the ONLY path that ever writes into
knowledge/skills/ — draft_skill (see app/agents/nodes/draft_skill.py) only
ever stages a proposal here; a human has to approve it first.
"""

import subprocess
from pathlib import Path

import psycopg
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.audit import log_action
from app.config import settings

router = APIRouter(prefix="/admin/review-queue", tags=["admin"])

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "knowledge" / "skills"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "forge-review-bot",
    "GIT_AUTHOR_EMAIL": "forge-review-bot@local",
    "GIT_COMMITTER_NAME": "forge-review-bot",
    "GIT_COMMITTER_EMAIL": "forge-review-bot@local",
}

# No real auth system exists yet (see docs/BUILD_SUMMARY.md — Okta/AD is not
# wired up); `role` is trusted straight from the request body, same trust
# model as team_id/persona/user_email elsewhere in this codebase. This is a
# stopgap, not real authorization — it stops an *accidental* wrong-role call
# from a well-behaved caller (e.g. the UI), not a malicious one that can
# simply lie about its role. Real authorization needs Phase 7.
ADMIN_ROLES = {"admin", "super_user"}


class ApproveSkillRequest(BaseModel):
    edited_content: str | None = None
    reviewer: str | None = None
    role: str | None = None


class RejectRequest(BaseModel):
    reviewer: str | None = None
    reason: str | None = None
    role: str | None = None


def _require_admin_role(conn, team_id: str | None, actor: str | None, role: str | None, action: str, target: str):
    if role not in ADMIN_ROLES:
        log_action(
            conn, team_id, actor, f"{action}_denied", target,
            {"reason": "role not in ADMIN_ROLES", "role": role},
        )
        conn.commit()
        raise HTTPException(status_code=403, detail=f"role {role!r} is not permitted to {action} (requires one of {sorted(ADMIN_ROLES)})")


def _parse_skill_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        raise HTTPException(status_code=400, detail="proposed content is missing YAML frontmatter")
    _, frontmatter, _ = content.split("---", 2)
    data = yaml.safe_load(frontmatter)
    for field in ("id", "team_id"):
        if field not in data:
            raise HTTPException(status_code=400, detail=f"skill frontmatter missing required field: {field}")
    return data


def _fetch_queue_row(cur, review_id: str) -> dict:
    cur.execute(
        "SELECT id, team_id, target, proposed_content, status FROM content_review_queue WHERE id = %s",
        (review_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="review queue entry not found")
    return {"id": row[0], "team_id": row[1], "target": row[2], "proposed_content": row[3], "status": row[4]}


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        env={**__import__("os").environ, **GIT_ENV},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


@router.get("")
def list_pending(team_id: str = "test"):
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, team_id, target, proposed_content, status
                FROM content_review_queue
                WHERE status = 'pending' AND team_id = %s
                ORDER BY created_at
                """,
                (team_id,),
            )
            rows = cur.fetchall()

    return [
        {
            "review_id": str(row[0]),
            "team_id": row[1],
            "target": row[2],
            "proposed_content": row[3],
            "status": row[4],
        }
        for row in rows
    ]


@router.post("/{review_id}/approve-skill")
def approve_skill(review_id: str, body: ApproveSkillRequest):
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            row = _fetch_queue_row(cur, review_id)
        _require_admin_role(conn, row["team_id"], body.reviewer, body.role, "approve_skill", review_id)

        with conn.cursor() as cur:
            if row["status"] != "pending":
                raise HTTPException(status_code=409, detail=f"review entry is already '{row['status']}'")
            if row["target"] != "new_skill":
                raise HTTPException(status_code=400, detail=f"approve-skill only handles target='new_skill', got '{row['target']}'")

            content = body.edited_content if body.edited_content is not None else row["proposed_content"]
            frontmatter = _parse_skill_frontmatter(content)

            team_dir = SKILLS_DIR / frontmatter["team_id"]
            team_dir.mkdir(parents=True, exist_ok=True)
            skill_path = team_dir / f"{frontmatter['id']}.md"
            skill_path.write_text(content, encoding="utf-8")

            relative_path = skill_path.relative_to(REPO_ROOT)
            _run_git(["add", str(relative_path)])
            _run_git(
                [
                    "commit",
                    "-m",
                    f"Approve skill '{frontmatter['id']}' from review queue {review_id}",
                ]
            )
            commit_hash = _run_git(["rev-parse", "HEAD"])

            cur.execute(
                """
                UPDATE content_review_queue
                SET status = 'approved', reviewer = %s, reviewed_at = now()
                WHERE id = %s
                """,
                (body.reviewer, review_id),
            )
            log_action(
                conn, row["team_id"], body.reviewer, "approve_skill", review_id,
                {"skill_id": frontmatter["id"], "commit": commit_hash, "role": body.role},
            )
        conn.commit()

    return {
        "status": "approved",
        "skill_path": str(relative_path),
        "commit": commit_hash,
        "skill_id": frontmatter["id"],
    }


@router.post("/{review_id}/reject")
def reject(review_id: str, body: RejectRequest):
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            row = _fetch_queue_row(cur, review_id)
        _require_admin_role(conn, row["team_id"], body.reviewer, body.role, "reject_skill", review_id)

        with conn.cursor() as cur:
            if row["status"] != "pending":
                raise HTTPException(status_code=409, detail=f"review entry is already '{row['status']}'")

            cur.execute(
                """
                UPDATE content_review_queue
                SET status = 'rejected', reviewer = %s, reviewed_at = now()
                WHERE id = %s
                """,
                (body.reviewer, review_id),
            )
            log_action(
                conn, row["team_id"], body.reviewer, "reject_skill", review_id,
                {"reason": body.reason, "role": body.role},
            )
        conn.commit()

    return {"status": "rejected", "review_id": review_id, "reason": body.reason}
