"""LangGraph agent graph for forge-api-gateway.

Flow:
    triage -> skill_match/rag_node/live_data_node (triage picks the first
    branch to try) -> if that branch doesn't confidently match and it's a
    knowledge-shaped question (not live data), the *other* knowledge branch
    (skill_match <-> rag_node) is tried as a second pass -> if neither
    confidently matches, draft_skill fires -> synthesize -> gates -> eval_score

triage is a mocked Haiku-style classifier (rule-based stand-in — swap for a
real model call later). synthesize returns a fixed mock string for now
(replaced with a real model call in a later step). live_data_node is a stub
until the Jira/SharePoint connectors are wired in.
"""

import re
from typing import Literal, TypedDict

import psycopg
from langgraph.graph import END, StateGraph
from pgvector.psycopg import register_vector

from app.agents.nodes.draft_skill import draft_skill_node
from app.agents.skill_match import match_skill
from app.config import settings
from app.connectors import jira_connector, sharepoint_connector
from app.rag.embed import embed_query

ROUTE_SKILL_MATCH = "skill_match"
ROUTE_RAG_NODE = "rag_node"
ROUTE_LIVE_DATA_NODE = "live_data_node"

RAG_TOP_K = 3
RAG_CONFIDENCE_THRESHOLD = 0.55  # calibrated against test/test_rag_retrieval.py

# Keyword heuristics standing in for a real Haiku-style intent classifier.
_LIVE_DATA_PATTERNS = [
    r"\bsprint\b",
    r"\bticket status\b",
    r"\bcurrent status\b",
    r"\btoday'?s\b",
    r"\bright now\b",
    r"\bthis week'?s\b",
    r"\bstory points\b",
    r"\bsharepoint\b",
    r"\bfind (the|a|an) .*(document|doc|deck|file|template)\b",
    r"\bshared documents\b",
]

_SKILL_PATTERNS = [
    r"\bcreate (a|an|the)? ?(follow-?up )?(jira )?ticket\b",
    r"\bfile a ticket\b",
    r"\bonboard\b",
    r"\bgenerate (a|an|the) (weekly )?report\b",
    r"\bprovision access\b",
]


class GraphState(TypedDict, total=False):
    question: str
    team_id: str
    persona: str
    user_email: str
    route: str
    route_confidence: float
    skill_result: dict
    rag_result: dict
    live_data_result: dict
    answer: str
    sources: list
    gate_passed: bool
    gate_reason: str
    score: float
    skill_gap_log_id: str
    review_queue_id: str


def triage(state: GraphState) -> GraphState:
    """Mocked classifier: real implementation would call a small, fast model
    (e.g. Claude Haiku) to classify intent. Rule-based here so the graph is
    fully testable without a live model credential."""
    question = state["question"].lower()

    route = ROUTE_RAG_NODE
    confidence = 0.55  # default/fallback confidence for the rag_node catch-all

    if any(re.search(p, question) for p in _SKILL_PATTERNS):
        route = ROUTE_SKILL_MATCH
        confidence = 0.92
    elif any(re.search(p, question) for p in _LIVE_DATA_PATTERNS):
        route = ROUTE_LIVE_DATA_NODE
        confidence = 0.88

    print(f"[triage] question={state['question']!r} -> route={route} (confidence={confidence})")

    return {"route": route, "route_confidence": confidence}


def _route_decision(state: GraphState) -> Literal["skill_match", "rag_node", "live_data_node"]:
    return state["route"]  # type: ignore[return-value]


def skill_match(state: GraphState) -> GraphState:
    result = match_skill(state["question"], state.get("persona", "business"), state.get("team_id"))
    return {"skill_result": result}


def rag_node(state: GraphState) -> GraphState:
    """Real pgvector similarity search against knowledge_chunks, scoped to
    the caller's team_id."""
    query_embedding = embed_query(state["question"])

    with psycopg.connect(settings.postgres_dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, content, 1 - (embedding <=> %s::vector) AS similarity
                FROM knowledge_chunks
                WHERE team_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, state.get("team_id", "test"), query_embedding, RAG_TOP_K),
            )
            rows = cur.fetchall()

    chunks = [{"chunk_id": r[0], "content": r[1], "similarity": float(r[2])} for r in rows]
    best_score = chunks[0]["similarity"] if chunks else 0.0

    return {
        "rag_result": {
            "matched": best_score >= RAG_CONFIDENCE_THRESHOLD,
            "chunks": chunks,
            "best_score": best_score,
        }
    }


_JIRA_PATTERNS = [
    r"\bsprint\b",
    r"\bticket status\b",
    r"\bstory points\b",
]


def live_data_node(state: GraphState) -> GraphState:
    question = state["question"].lower()
    team_id = state.get("team_id", "test")

    if any(re.search(p, question) for p in _JIRA_PATTERNS):
        data = jira_connector.get_sprint_status(team_id)
        return {
            "live_data_result": {
                "matched": True,
                "connector": "jira",
                "data": data,
                "sources": [
                    {
                        "source_type": "jira",
                        "source_ref": f"board-{data['board_id']}/sprint-{data['sprint_id']}",
                        "title": data["sprint_name"],
                        "url": data["url"],
                    }
                ],
            }
        }

    _SHAREPOINT_PATTERNS = [
        r"\bsharepoint\b",
        r"\bfind (the|a|an) .*(document|doc|deck|file|template)\b",
        r"\bshared documents\b",
    ]
    if any(re.search(p, question) for p in _SHAREPOINT_PATTERNS):
        user_email = state.get("user_email", "unknown-user@forge.example")
        results = sharepoint_connector.search_documents(state["question"], user_email)
        return {
            "live_data_result": {
                "matched": bool(results),
                "connector": "sharepoint",
                "data": results,
                "sources": [
                    {
                        "source_type": "sharepoint",
                        "source_ref": doc["item_id"],
                        "title": doc["title"],
                        "url": doc["url"],
                    }
                    for doc in results
                ],
            }
        }

    return {
        "live_data_result": {
            "matched": False,
            "reason": "no live connector matched this question",
        }
    }


def draft_skill(state: GraphState) -> GraphState:
    return draft_skill_node(state)


def synthesize(state: GraphState) -> GraphState:
    """Answer text is still a fixed mock string (no model credential wired
    up yet) but source attribution is real: it reflects whichever branch
    actually matched, so message_sources/citations are accurate even before
    the real model call lands."""
    sources: list = []

    live_result = state.get("live_data_result") or {}
    rag_result = state.get("rag_result") or {}
    skill_result = state.get("skill_result") or {}

    if live_result.get("matched"):
        sources = live_result.get("sources", [])
    elif rag_result.get("matched"):
        sources = [
            {"source_type": "knowledge_chunk", "source_ref": c["chunk_id"], "score": c["similarity"]}
            for c in rag_result.get("chunks", [])[:3]
        ]
    elif skill_result.get("matched"):
        sources = [{"source_type": "skill", "source_ref": skill_result["skill_id"]}]

    return {
        "answer": "[MOCK ANSWER] This is a placeholder response from synthesize().",
        "sources": sources,
    }


def gates(state: GraphState) -> GraphState:
    """Policy checks before returning an answer. Placeholder pass-through —
    real persona/confidence gating comes with skill_match/rag_node."""
    return {"gate_passed": True, "gate_reason": "no gating rules enforced yet"}


def eval_score(state: GraphState) -> GraphState:
    """Placeholder quality score — real scoring comes with eval_case_log
    wiring in a later step."""
    return {"score": 0.5}


def _after_skill_match(state: GraphState) -> Literal["synthesize", "rag_node", "draft_skill"]:
    if state["skill_result"]["matched"]:
        return "synthesize"
    if "rag_result" in state:
        return "draft_skill"
    return "rag_node"


def _after_rag_node(state: GraphState) -> Literal["synthesize", "skill_match", "draft_skill"]:
    if state["rag_result"]["matched"]:
        return "synthesize"
    if "skill_result" in state:
        return "draft_skill"
    return "skill_match"


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("triage", triage)
    graph.add_node("skill_match", skill_match)
    graph.add_node("rag_node", rag_node)
    graph.add_node("live_data_node", live_data_node)
    graph.add_node("draft_skill", draft_skill)
    graph.add_node("synthesize", synthesize)
    graph.add_node("gates", gates)
    graph.add_node("eval_score", eval_score)

    graph.set_entry_point("triage")
    graph.add_conditional_edges(
        "triage",
        _route_decision,
        {
            ROUTE_SKILL_MATCH: "skill_match",
            ROUTE_RAG_NODE: "rag_node",
            ROUTE_LIVE_DATA_NODE: "live_data_node",
        },
    )
    graph.add_conditional_edges(
        "skill_match",
        _after_skill_match,
        {"synthesize": "synthesize", "rag_node": "rag_node", "draft_skill": "draft_skill"},
    )
    graph.add_conditional_edges(
        "rag_node",
        _after_rag_node,
        {"synthesize": "synthesize", "skill_match": "skill_match", "draft_skill": "draft_skill"},
    )
    graph.add_edge("live_data_node", "synthesize")
    graph.add_edge("draft_skill", "gates")  # already set its own answer, skip the mock synthesize
    graph.add_edge("synthesize", "gates")
    graph.add_edge("gates", "eval_score")
    graph.add_edge("eval_score", END)

    return graph.compile()


def run_question(question: str, team_id: str = "test", persona: str = "business", user_email: str = "unknown-user@forge.example") -> GraphState:
    app = build_graph()
    return app.invoke({"question": question, "team_id": team_id, "persona": persona, "user_email": user_email})
