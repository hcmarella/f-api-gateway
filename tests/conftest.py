import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
import pytest

from app.config import settings


@pytest.fixture
def db_conn():
    conn = psycopg.connect(settings.postgres_dsn)
    yield conn
    conn.close()


@pytest.fixture
def scratch_team(db_conn):
    """A throwaway team_id, cleaned up (knowledge_chunks, documents,
    content_review_queue, skill_gap_log, audit_log, teams) at teardown.
    Use this for tests that need to plant synthetic content without
    polluting the real 'test'/'host' teams."""
    team_id = f"pytest-scratch-{uuid.uuid4().hex[:8]}"
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO teams (team_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (team_id, team_id))
    db_conn.commit()

    yield team_id

    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM knowledge_chunks WHERE team_id = %s", (team_id,))
        cur.execute("DELETE FROM documents WHERE team_id = %s", (team_id,))
        cur.execute("DELETE FROM content_review_queue WHERE team_id = %s", (team_id,))
        cur.execute("DELETE FROM skill_gap_log WHERE team_id = %s", (team_id,))
        cur.execute("DELETE FROM audit_log WHERE team_id = %s", (team_id,))
        cur.execute("DELETE FROM teams WHERE team_id = %s", (team_id,))
    db_conn.commit()
