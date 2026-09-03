"""Syncs Jira projects/tickets/dependencies into the Neo4j graph test lane.

This is the entity-relationship data pgvector fundamentally can't represent
— (:Project)-[:DEPENDS_ON]->(:Project), (:Ticket)-[:BLOCKS]->(:Ticket) — as
opposed to the flat, unrelated document chunks that both pgvector and the
earlier :Chunk-based Neo4j setup (tests/test_graphdb_vs_vector.py) index.

Two passes deliberately: all Project/Ticket/Person nodes are MERGEd first,
then BLOCKS edges — otherwise a ticket referenced by an earlier ticket's
`blocks` list but not yet processed would get created as a bare node
missing its title/status/project.
"""

import logging

from app.connectors import jira_connector
from app.graph.neo4j_client import get_driver

logger = logging.getLogger("graph.ingestion.jira")


def sync_jira_to_graph(team_id: str) -> dict:
    projects = jira_connector.get_projects(team_id)
    tickets = jira_connector.get_all_tickets(team_id)

    driver = get_driver()
    with driver.session() as session:
        session.run("MERGE (team:Team {id: $team_id})", team_id=team_id)

        for project in projects:
            session.run(
                """
                MERGE (p:Project {id: $id})
                SET p.name = $name, p.team_id = $team_id
                MERGE (team:Team {id: $team_id})
                MERGE (p)-[:OWNED_BY]->(team)
                """,
                id=project["id"], name=project["name"], team_id=team_id,
            )
            for dep_id in project.get("depends_on_project_ids", []):
                session.run(
                    """
                    MERGE (p:Project {id: $id})
                    MERGE (dep:Project {id: $dep_id})
                    MERGE (p)-[:DEPENDS_ON]->(dep)
                    """,
                    id=project["id"], dep_id=dep_id,
                )

        for ticket in tickets:
            session.run(
                """
                MERGE (t:Ticket {id: $id})
                SET t.title = $title, t.status = $status, t.team_id = $team_id, t.source = 'jira'
                MERGE (p:Project {id: $project_id})
                MERGE (t)-[:BELONGS_TO]->(p)
                MERGE (person:Person {id: $assignee_id})
                SET person.name = $assignee_name
                MERGE (person)-[:ASSIGNED_TO]->(t)
                """,
                id=ticket["id"], title=ticket["title"], status=ticket["status"], team_id=team_id,
                project_id=ticket["project_id"], assignee_id=ticket["assignee_id"], assignee_name=ticket["assignee_name"],
            )

        # Second pass: BLOCKS edges, now that every ticket node has its full properties.
        for ticket in tickets:
            for blocked_id in ticket.get("blocks", []):
                session.run(
                    """
                    MATCH (t1:Ticket {id: $id1})
                    MERGE (t2:Ticket {id: $id2})
                    MERGE (t1)-[:BLOCKS]->(t2)
                    """,
                    id1=ticket["id"], id2=blocked_id,
                )

    logger.info(
        "jira_to_graph: synced %d project(s), %d ticket(s) for team_id=%r",
        len(projects), len(tickets), team_id,
    )
    return {"projects": len(projects), "tickets": len(tickets)}
