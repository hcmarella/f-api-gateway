"""Syncs SharePoint files into the Neo4j graph test lane, linking each file
to the project it's associated with (sharepoint_connector.list_files_for_team
— a bulk listing, distinct from the live per-query search_documents() used
by live_data_node).

Same MATCH-not-MERGE discipline as confluence_to_graph.py: only links to a
project that already exists from jira_to_graph, never fabricates one.
"""

import logging

from app.connectors import sharepoint_connector
from app.graph.neo4j_client import get_driver

logger = logging.getLogger("graph.ingestion.sharepoint")


def sync_sharepoint_to_graph(team_id: str) -> dict:
    files = sharepoint_connector.list_files_for_team(team_id)

    driver = get_driver()
    linked = 0
    with driver.session() as session:
        for file in files:
            session.run(
                """
                MERGE (f:File {id: $id})
                SET f.title = $title, f.team_id = $team_id, f.source = 'sharepoint'
                """,
                id=file["item_id"], title=file["title"], team_id=team_id,
            )
            if file.get("project_id"):
                result = session.run(
                    """
                    MATCH (f:File {id: $file_id}), (p:Project {id: $project_id})
                    MERGE (f)-[:RELATED_TO]->(p)
                    RETURN p
                    """,
                    file_id=file["item_id"], project_id=file["project_id"],
                )
                if result.single() is not None:
                    linked += 1

    logger.info(
        "sharepoint_to_graph: synced %d file(s), %d project link(s) for team_id=%r",
        len(files), linked, team_id,
    )
    return {"files": len(files), "project_links": linked}
