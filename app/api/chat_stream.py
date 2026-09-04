"""POST /ai/chat/stream — Server-Sent Events version of /ai/chat.

Deliberately uses the compiled LangGraph's own `.stream(stream_mode="updates")`
rather than re-implementing a simplified linear sequence of node calls (the
"triage -> route -> synthesize -> gates" shape you'd write from scratch).
That simplified version would silently skip this graph's real conditional
topology — the skill_match<->rag_node cascading second-attempt fallback, and
draft_skill firing when both fail (see app/agents/graph.py's module
docstring). Streaming from the real compiled graph means /ai/chat and
/ai/chat/stream can never drift into answering differently for the same
question; they run the identical graph, one just narrates it.

Persistence and response-shaping are shared with /ai/chat via
persist_and_build_response — this endpoint only adds progress events on top.
"""

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.graph import build_graph
from app.api.chat import ChatRequest, persist_and_build_response

router = APIRouter(prefix="/ai", tags=["chat"])

STAGE_LABELS = {
    "triage": "Understanding your question...",
    "skill_match": "Checking for a matching skill...",
    "rag_node": "Searching the knowledge base...",
    "live_data_node": "Checking live systems...",
    "draft_skill": "No confident match — logging the gap...",
    "synthesize": "Generating an answer...",
    "gates": "Checking sources...",
    "eval_score": "Finishing up...",
}


@router.post("/chat/stream")
def chat_stream(body: ChatRequest):
    def event_generator():
        graph = build_graph()
        initial_state = {
            "question": body.question,
            "team_id": body.team_id,
            "persona": body.persona,
            "user_email": body.user_email,
        }
        final_state: dict = {}

        for step in graph.stream(initial_state, stream_mode="updates"):
            for node_name, update in step.items():
                final_state.update(update)
                label = STAGE_LABELS.get(node_name, node_name)
                yield f"data: {json.dumps({'stage': node_name, 'label': label})}\n\n"

        response = persist_and_build_response(body, final_state, action="chat_stream")
        yield f"data: {json.dumps({'stage': 'complete', 'result': response.model_dump()})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
