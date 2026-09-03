"""Sanity check + threshold calibration for rag_node's pgvector search.
Run: python test/test_rag_retrieval.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.graph import rag_node

RELEVANT_QUESTIONS = [
    "What's our policy on data retention for conversations?",
    "How long does the reset link stay valid for password resets?",
    "What severity level requires paging on-call immediately?",
]

NONSENSE_QUESTIONS = [
    "What is the airspeed velocity of an unladen swallow?",
    "Can you recommend a good recipe for banana bread?",
]


def main():
    print("--- Questions that SHOULD match existing knowledge ---")
    for q in RELEVANT_QUESTIONS:
        result = rag_node({"question": q, "team_id": "test"})["rag_result"]
        print(f"  best_score={result['best_score']:.4f} matched={result['matched']}  {q!r}")
        if result["chunks"]:
            print(f"    top chunk_id={result['chunks'][0]['chunk_id']}")

    print("\n--- Questions that should NOT match anything ---")
    for q in NONSENSE_QUESTIONS:
        result = rag_node({"question": q, "team_id": "test"})["rag_result"]
        print(f"  best_score={result['best_score']:.4f} matched={result['matched']}  {q!r}")


if __name__ == "__main__":
    main()
