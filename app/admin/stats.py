"""Read-only operational stats for the gateway's own dashboard (see
GET /dashboard). Deliberately separate from Forge-UI — this is an ops/
monitoring surface for the gateway itself, not a business-facing feature.
"""

import psycopg
from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/admin/stats", tags=["admin"])


@router.get("")
def stats():
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            # --- Routing / chat activity ---------------------------------
            cur.execute(
                "SELECT triage_route, count(*) FROM messages WHERE role = 'assistant' "
                "GROUP BY triage_route ORDER BY count(*) DESC"
            )
            route_distribution = [{"route": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute(
                "SELECT m.message_id, m.triage_route, m.confidence, m.created_at, c.team_id, "
                "left(m.content, 120) "
                "FROM messages m JOIN conversations c ON c.conversation_id = m.conversation_id "
                "WHERE m.role = 'assistant' ORDER BY m.created_at DESC LIMIT 20"
            )
            recent_messages = [
                {"message_id": str(r[0]), "route": r[1], "confidence": r[2], "created_at": r[3].isoformat(),
                 "team_id": r[4], "answer_preview": r[5]}
                for r in cur.fetchall()
            ]

            cur.execute(
                "SELECT team_id, actor, action, target, created_at FROM audit_log "
                "ORDER BY created_at DESC LIMIT 20"
            )
            recent_audit = [
                {"team_id": r[0], "actor": r[1], "action": r[2], "target": r[3], "created_at": r[4].isoformat()}
                for r in cur.fetchall()
            ]

            cur.execute("SELECT count(*) FROM audit_log WHERE action LIKE '%_denied'")
            denied_count = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM messages WHERE role = 'assistant'")
            total_messages = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM conversations")
            total_conversations = cur.fetchone()[0]

            # --- Review queue ----------------------------------------------
            cur.execute("SELECT status, count(*) FROM content_review_queue GROUP BY status")
            review_queue_by_status = [{"status": r[0], "count": r[1]} for r in cur.fetchall()]

            cur.execute(
                "SELECT id, team_id, target, status, created_at FROM content_review_queue "
                "ORDER BY created_at DESC LIMIT 20"
            )
            recent_review_queue = [
                {"id": str(r[0]), "team_id": r[1], "target": r[2], "status": r[3], "created_at": r[4].isoformat()}
                for r in cur.fetchall()
            ]

            # --- Ingestion / sync pipeline -----------------------------------
            cur.execute(
                "SELECT id, team_id, connector, status, documents_processed, chunks_upserted, "
                "error, started_at, finished_at FROM sync_runs ORDER BY started_at DESC LIMIT 20"
            )
            sync_runs = [
                {
                    "id": str(r[0]), "team_id": r[1], "connector": r[2], "status": r[3],
                    "documents_processed": r[4], "chunks_upserted": r[5], "error": r[6],
                    "started_at": r[7].isoformat() if r[7] else None,
                    "finished_at": r[8].isoformat() if r[8] else None,
                }
                for r in cur.fetchall()
            ]

            cur.execute("SELECT count(*) FROM knowledge_chunks")
            total_chunks = cur.fetchone()[0]
            cur.execute("SELECT team_id, count(*) FROM knowledge_chunks GROUP BY team_id ORDER BY count(*) DESC")
            chunks_by_team = [{"team_id": r[0], "count": r[1]} for r in cur.fetchall()]

            # --- pgvector vs Neo4j eval comparison ---------------------------
            cur.execute(
                "SELECT retrieval_engine, round(avg(confidence)::numeric, 4), "
                "round(avg(latency_ms)::numeric, 2), round(avg(passed::int)::numeric, 2), count(*) "
                "FROM eval_case_log GROUP BY retrieval_engine ORDER BY retrieval_engine"
            )
            eval_comparison = [
                {"engine": r[0], "avg_confidence": float(r[1]) if r[1] is not None else None,
                 "avg_latency_ms": float(r[2]) if r[2] is not None else None,
                 "pass_rate": float(r[3]) if r[3] is not None else None, "n": r[4]}
                for r in cur.fetchall()
            ]

    return {
        "routing": {
            "distribution": route_distribution,
            "recent_messages": recent_messages,
            "total_messages": total_messages,
            "total_conversations": total_conversations,
        },
        "audit": {
            "recent": recent_audit,
            "denied_count": denied_count,
        },
        "review_queue": {
            "by_status": review_queue_by_status,
            "recent": recent_review_queue,
        },
        "sync_pipeline": {
            "recent_runs": sync_runs,
            "total_chunks": total_chunks,
            "chunks_by_team": chunks_by_team,
        },
        "eval_comparison": eval_comparison,
    }
