"""Populates the Neo4j graph test lane (app/graph/) with real entity
relationships for team_id='host' (and 'test', which owns the cross-team
dependency payments-core project) and runs the dependency-traversal query
that's the actual case for graph over vector search.

Requires docker-compose.test.yml's neo4j-test service running.
Run: python test/test_graph_entity_ingestion.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph.ingestion.confluence_to_graph import sync_confluence_to_graph
from app.graph.ingestion.jira_to_graph import sync_jira_to_graph
from app.graph.ingestion.sharepoint_to_graph import sync_sharepoint_to_graph
from app.graph.queries.dependency_traversal import blocking_tickets_from_cross_team_dependencies
from app.graph.queries.team_scoped_queries import get_team_projects, get_team_tickets


def main():
    print("=== Syncing Jira (projects/tickets/dependencies) ===")
    # 'test' first: 'host'-platform depends on 'test'-owned payments-core,
    # so that project must exist before host's DEPENDS_ON edge resolves.
    print("test:", sync_jira_to_graph("test"))
    print("host:", sync_jira_to_graph("host"))

    print("\n=== Syncing Confluence (pages -> ticket references) ===")
    print("host:", sync_confluence_to_graph("host"))

    print("\n=== Syncing SharePoint (files -> project associations) ===")
    print("host:", sync_sharepoint_to_graph("host"))

    print("\n=== Team-scoped reads (tenant isolation, same discipline as pgvector) ===")
    host_projects = get_team_projects("host")
    test_projects = get_team_projects("test")
    print(f"host projects: {host_projects}")
    print(f"test projects: {test_projects}")
    assert "payments-core" not in {p["id"] for p in host_projects}, "host's project list leaked test's payments-core"
    assert "host-platform" not in {p["id"] for p in test_projects}, "test's project list leaked host's host-platform"
    print("[PASS] team-scoped project reads are isolated")

    print(f"\nhost tickets: {get_team_tickets('host')}")

    print("\n=== The multi-hop query: tickets blocking host's work that trace to a cross-team dependency ===")
    results = blocking_tickets_from_cross_team_dependencies("host")
    for row in results:
        print(f"  {row['blocking_ticket']} ({row['blocking_title']!r}) blocks {row['blocked_ticket']} "
              f"({row['blocked_title']!r}) -> depends on {row['other_project']} owned by team {row['other_team']!r}")

    assert len(results) >= 1, "expected at least one cross-team dependency chain from the seeded mock data"
    assert any(r["other_team"] == "test" for r in results), "expected the chain to trace to team 'test' (payments-core)"
    print("\n[PASS] multi-hop traversal found the real cross-team dependency chain")


if __name__ == "__main__":
    main()
