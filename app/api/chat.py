"""POST /ai/chat — runs a question through the agent graph and persists the
conversation turn, including source attribution, to Postgres."""

import psycopg
from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.graph import run_question
from app.audit import log_action
from app.config import settings

router = APIRouter(prefix="/ai", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    team_id: str = "test"
    persona: str = "business"
    user_email: str = "unknown-user@forge.example"
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    route: str
    sources: list
    gate_passed: bool
    score: float
    conversation_id: str
    message_id: str


def persist_and_build_response(body: ChatRequest, result: dict, action: str = "chat") -> ChatResponse:
    """Shared by POST /ai/chat and POST /ai/chat/stream so both endpoints
    persist and shape the final response identically — the streaming
    endpoint only adds progress events on top of this, it doesn't get its
    own copy of the persistence logic to drift out of sync."""
    with psycopg.connect(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            if body.conversation_id:
                conversation_id = body.conversation_id
            else:
                cur.execute(
                    "INSERT INTO conversations (team_id, title) VALUES (%s, %s) RETURNING conversation_id",
                    (body.team_id, body.question[:80]),
                )
                conversation_id = str(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO messages (conversation_id, role, content, triage_route, confidence)
                VALUES (%s, 'assistant', %s, %s, %s)
                RETURNING message_id
                """,
                (conversation_id, result["answer"], result.get("route"), result.get("score")),
            )
            message_id = str(cur.fetchone()[0])

            for source in result.get("sources", []):
                cur.execute(
                    """
                    INSERT INTO message_sources (message_id, source_type, source_ref, title, url, score)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message_id,
                        source.get("source_type"),
                        source.get("source_ref"),
                        source.get("title"),
                        source.get("url"),
                        source.get("score"),
                    ),
                )

            log_action(
                conn,
                team_id=body.team_id,
                actor=body.user_email,
                action=action,
                target=result.get("route"),
                details={
                    "question": body.question,
                    "persona": body.persona,
                    "route": result.get("route"),
                    "gate_passed": result.get("gate_passed"),
                    "score": result.get("score"),
                    "sources": result.get("sources", []),
                },
            )
        conn.commit()

    return ChatResponse(
        answer=result["answer"],
        route=result["route"],
        sources=result.get("sources", []),
        gate_passed=result.get("gate_passed", False),
        score=result.get("score", 0.0),
        conversation_id=conversation_id,
        message_id=message_id,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    result = run_question(body.question, team_id=body.team_id, persona=body.persona, user_email=body.user_email)
    return persist_and_build_response(body, result)
