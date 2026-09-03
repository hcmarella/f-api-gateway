"""Syncs Confluence pages into the Neo4j graph test lane, linking each page
to the tickets it mentions via real regex extraction
(confluence_connector.extract_ticket_references — not mocked).

Deliberately uses MATCH, not MERGE, for the referenced ticket: a text
mention isn't authoritative ticket data, so this only links to a ticket
that already exists from jira_to_graph — it never fabricates a Ticket node
from a string match. Run jira_to_graph before confluence_to_graph for a
given team if you want references to actually resolve.
"""

import logging

from app.connectors import confluence_connector
from app.graph.neo4j_client import get_driver

logger = logging.getLogger("graph.ingestion.confluence")


def sync_confluence_to_graph(team_id: str) -> dict:
    pages = confluence_connector.list_pages(team_id)

    driver = get_driver()
    linked = 0
    with driver.session() as session:
        for page in pages:
            session.run(
                """
                MERGE (d:Document {id: $id})
                SET d.title = $title, d.team_id = $team_id, d.source = 'confluence'
                """,
                id=page["page_id"], title=page["title"], team_id=team_id,
            )
            for ticket_id in confluence_connector.extract_ticket_references(page["body"]):
                result = session.run(
                    """
                    MATCH (d:Document {id: $doc_id}), (t:Ticket {id: $ticket_id})
                    MERGE (d)-[:REFERENCES]->(t)
                    RETURN t
                    """,
                    doc_id=page["page_id"], ticket_id=ticket_id,
                )
                if result.single() is not None:
                    linked += 1

    logger.info(
        "confluence_to_graph: synced %d page(s), %d reference link(s) for team_id=%r",
        len(pages), linked, team_id,
    )
    return {"pages": len(pages), "references_linked": linked}
