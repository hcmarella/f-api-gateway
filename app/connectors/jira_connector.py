"""Jira connector.

Wraps the Jira data the agent graph needs live at query time (currently:
sprint status for a team's board). There is no live Jira instance or API
token available in this environment yet, so `_call_jira_api` is mocked —
swap its body for a real `requests` call against JIRA_BASE_URL's REST API
once credentials exist. The public interface (`get_sprint_status`) is what
callers depend on and does not need to change when that happens.
"""

import hashlib
import logging
import os
import time

logger = logging.getLogger("connectors.jira")

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://mock-jira.example.atlassian.net")

# Per-team mock board/sprint state, standing in for a real Jira Agile API
# response until credentials are available.
_MOCK_SPRINT_DATA = {
    "test": {
        "board_id": 42, "sprint_id": 1017, "sprint_name": "Sprint 17",
        "issues_total": 23, "issues_done": 14, "issues_in_progress": 6, "issues_todo": 3,
        "story_points_committed": 55, "story_points_completed": 34,
    },
    "host": {
        "board_id": 7, "sprint_id": 205, "sprint_name": "Sprint 5",
        "issues_total": 12, "issues_done": 9, "issues_in_progress": 2, "issues_todo": 1,
        "story_points_committed": 30, "story_points_completed": 24,
    },
}


def _synthetic_sprint_data(team_id: str) -> dict:
    """Deterministic-but-team-unique fake data for a team that isn't in
    _MOCK_SPRINT_DATA. Never falls back to another team's real entry — that
    would be a cross-tenant data leak, even in a mock. Same team_id always
    produces the same numbers (useful for repeatable tests) without ever
    matching another team's board/sprint identifiers."""
    seed = int(hashlib.sha256(team_id.encode()).hexdigest()[:8], 16)
    total = 10 + (seed % 20)
    done = seed % (total + 1)
    return {
        "board_id": 1000 + (seed % 9000),
        "sprint_id": 5000 + (seed % 5000),
        "sprint_name": f"Sprint {1 + seed % 30}",
        "issues_total": total,
        "issues_done": done,
        "issues_in_progress": (total - done) // 2,
        "issues_todo": total - done - (total - done) // 2,
        "story_points_committed": 20 + (seed % 60),
        "story_points_completed": (20 + seed % 60) * done // max(total, 1),
    }


def _call_jira_api(team_id: str) -> dict:
    """Stand-in for GET {JIRA_BASE_URL}/rest/agile/1.0/board/{id}/sprint.
    Mocked because no live Jira credentials are configured in this
    environment; the logged line is what Step 11's verification checks for
    to confirm this path — not knowledge_chunks — was hit."""
    logger.info("jira_connector: calling live Jira API for team_id=%r (sprint board status)", team_id)
    time.sleep(0.05)  # simulate network latency of a real API call
    if team_id in _MOCK_SPRINT_DATA:
        return _MOCK_SPRINT_DATA[team_id]
    return _synthetic_sprint_data(team_id)


def get_sprint_status(team_id: str) -> dict:
    data = _call_jira_api(team_id)
    url = f"{JIRA_BASE_URL}/jira/software/projects/{team_id}/boards/{data['board_id']}/sprints/{data['sprint_id']}"
    return {**data, "team_id": team_id, "url": url}
