"""Generic team-scoped graph reads — same tenant-isolation discipline as
pgvector's `WHERE team_id = %s` (see tests/test_rbac_leakage.py). Every
query here filters by team_id at the query layer, not after the fact."""

from app.graph.neo4j_client import get_driver


def get_team_projects(team_id: str) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (p:Project)-[:OWNED_BY]->(:Team {id: $team_id}) RETURN p.id AS id, p.name AS name",
            team_id=team_id,
        )
        return [dict(r) for r in result]


def get_team_tickets(team_id: str) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (t:Ticket {team_id: $team_id}) RETURN t.id AS id, t.title AS title, t.status AS status",
            team_id=team_id,
        )
        return [dict(r) for r in result]


def get_team_documents(team_id: str) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (d:Document {team_id: $team_id}) RETURN d.id AS id, d.title AS title",
            team_id=team_id,
        )
        return [dict(r) for r in result]


def get_team_files(team_id: str) -> list[dict]:
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (f:File {team_id: $team_id}) RETURN f.id AS id, f.title AS title",
            team_id=team_id,
        )
        return [dict(r) for r in result]
