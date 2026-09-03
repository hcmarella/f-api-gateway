"""The multi-hop query that's the actual case for graph over vector search:
tickets belonging to a team's project that block other tickets, where the
blocked ticket's project depends on a project owned by a DIFFERENT team.

Answering this with pgvector would need multiple separate similarity
searches (tickets, then projects, then dependencies) plus a human
stitching the results together — a single Cypher traversal does it in one
query, because the relationships (BELONGS_TO, BLOCKS, DEPENDS_ON, OWNED_BY)
are real graph edges, not inferred from text similarity.
"""

from app.graph.neo4j_client import get_driver


def blocking_tickets_from_cross_team_dependencies(team_id: str) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (myTeam:Team {id: $team_id})<-[:OWNED_BY]-(p:Project)<-[:BELONGS_TO]-(t:Ticket)
            MATCH (t)-[:BLOCKS]->(blocked:Ticket)-[:BELONGS_TO]->(myProject:Project)
            OPTIONAL MATCH (myProject)-[:DEPENDS_ON]->(otherProject:Project)-[:OWNED_BY]->(otherTeam:Team)
            WHERE otherTeam.id <> $team_id
            RETURN t.id AS blocking_ticket, t.title AS blocking_title,
                   blocked.id AS blocked_ticket, blocked.title AS blocked_title,
                   otherProject.id AS other_project, otherTeam.id AS other_team
            """,
            team_id=team_id,
        )
        return [dict(r) for r in result]
