"""Shared Neo4j driver for app/graph/ — the entity-relationship graph test
lane for team_id='host' (projects/tickets/documents/files, distinct from the
flat vector-indexed :Chunk nodes tests/test_graphdb_vs_vector.py uses for
retrieval comparison; the two coexist in the same neo4j-test instance
without conflict since they use different node labels).

Points at the test-only neo4j-test service (docker-compose.test.yml) by
default. That file's own header is the source of truth: this container is
NEVER added to the main docker-compose.yml.
"""

import os

from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j-test:7687")
NEO4J_AUTH = (
    os.environ.get("NEO4J_USER", "neo4j"),
    os.environ.get("NEO4J_PASSWORD", "testpassword123"),
)

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
    return _driver


def close_driver():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
