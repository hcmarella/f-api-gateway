"""Central audit_log writer. Every request that makes an authorization or
routing decision should log one row here — including denials, which are the
ones most likely to matter later and easiest to forget to log."""

import json

import psycopg


def log_action(conn: psycopg.Connection, team_id: str | None, actor: str | None, action: str, target: str | None = None, details: dict | None = None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (team_id, actor, action, target, details) VALUES (%s, %s, %s, %s, %s)",
            (team_id, actor, action, target, json.dumps(details or {})),
        )
