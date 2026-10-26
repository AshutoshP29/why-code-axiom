"""Neo4j driver construction for the two targets: Aura (real data) and the local test container."""

import os
from dataclasses import dataclass, field

from neo4j import Driver, GraphDatabase

from whycode.config import Settings


@dataclass(frozen=True)
class Neo4jTarget:
    name: str
    uri: str
    username: str
    password: str = field(repr=False)
    database: str

    def driver(self) -> Driver:
        return GraphDatabase.driver(
            self.uri, auth=(self.username, self.password), connection_timeout=15
        )


def aura_target(settings: Settings) -> Neo4jTarget:
    return Neo4jTarget(
        name="aura",
        uri=settings.neo4j_uri,
        username=settings.neo4j_username,
        password=settings.neo4j_password.get_secret_value(),
        database=settings.neo4j_database,
    )


def local_test_target() -> Neo4jTarget:
    """The docker-compose neo4j-test container. Dev-only credentials, overridable by env var."""
    return Neo4jTarget(
        name="test",
        uri=os.environ.get("WHYCODE_TEST_NEO4J_URI", "bolt://localhost:7688"),
        username=os.environ.get("WHYCODE_TEST_NEO4J_USER", "neo4j"),
        password=os.environ.get("WHYCODE_TEST_NEO4J_PASS", "whycode_dev_only"),
        database="neo4j",
    )
