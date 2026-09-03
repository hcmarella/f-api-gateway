"""Confirms each branch of the agent graph's triage routing fires correctly.
Run: python -m test.test_graph_routing (or python test/test_graph_routing.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.graph import (
    ROUTE_LIVE_DATA_NODE,
    ROUTE_RAG_NODE,
    ROUTE_SKILL_MATCH,
    run_question,
)

CASES = [
    ("Create a follow-up Jira ticket for this bug", ROUTE_SKILL_MATCH),
    ("What's our policy on data retention for conversations?", ROUTE_RAG_NODE),
    ("What's the current sprint status for the platform team?", ROUTE_LIVE_DATA_NODE),
]


def main():
    failures = []
    for question, expected_route in CASES:
        result = run_question(question)
        actual_route = result["route"]
        status = "PASS" if actual_route == expected_route else "FAIL"
        if status == "FAIL":
            failures.append((question, expected_route, actual_route))
        print(f"[{status}] expected={expected_route} actual={actual_route}")
        print(f"       answer={result['answer']!r} gate_passed={result['gate_passed']} score={result['score']}")
        print()

    routes_seen = {r for _, _, r in [(q, e, run_question(q)["route"]) for q, e in CASES]}
    print(f"Distinct routes exercised: {sorted(routes_seen)}")
    assert len(routes_seen) == 3, "expected all 3 branches to be exercised, not defaulting to one path"

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for q, expected, actual in failures:
            print(f"  {q!r}: expected {expected}, got {actual}")
        sys.exit(1)
    print("All routing cases passed.")


if __name__ == "__main__":
    main()
