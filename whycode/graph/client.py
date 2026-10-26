"""Neo4j driver construction for the two targets: Aura (real data) and the local test container."""

import os
import ssl
from dataclasses import dataclass, field

import certifi
from neo4j import Driver, GraphDatabase

from whycode.config import Settings

_SECURE_SUFFIX = "+s://"


def tls_args(uri: str) -> tuple[str, dict]:
    """Turn a "+s" URI into a plain one plus an explicit, fully verifying TLS context.

    Python on Windows checks only the Windows certificate store, which fetches some root CAs
    lazily and so may lack the one Aura's certificate chains to. Trusting certifi's bundle as
    well fixes that without weakening verification. The driver only accepts a custom
    ssl_context with the non-"+s" scheme, hence the rewrite.
    """
    scheme, sep, rest = uri.partition(_SECURE_SUFFIX)
    if not sep:
        return uri, {}
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_default_certs()  # keep OS-installed CAs too (e.g. corporate roots)
    return f"{scheme}://{rest}", {"ssl_context": ctx}


@dataclass(frozen=True)
class Neo4jTarget:
    name: str
    uri: str
    username: str
    password: str = field(repr=False)
    database: str

    def driver(self) -> Driver:
        uri, extra = tls_args(self.uri)
        return GraphDatabase.driver(
            uri, auth=(self.username, self.password), connection_timeout=15, **extra
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
