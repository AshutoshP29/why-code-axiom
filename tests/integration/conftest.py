import pytest

from whycode.graph.client import local_test_target


@pytest.fixture(scope="session")
def neo4j_test():
    """Driver for the docker-compose neo4j-test container. Never Aura."""
    target = local_test_target()
    driver = target.driver()
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        pytest.fail(
            f"neo4j-test container unreachable at {target.uri} ({exc}); docker compose up -d"
        )
    yield driver, target.database
    driver.close()


TEST_REPO = "test/fixture"


@pytest.fixture
def raw_store():
    """RawStore on the docker-compose Postgres; test/fixture rows are removed before and after."""
    import os

    from whycode.ingest.store import RawStore

    dsn = os.environ.get(
        "WHYCODE_TEST_POSTGRES_DSN",
        "postgresql://whycode:whycode_dev_only@127.0.0.1:5433/whycode",
    )
    try:
        store = RawStore.connect(dsn)
    except Exception as exc:
        pytest.fail(f"Postgres unreachable ({type(exc).__name__}); docker compose up -d")
    store.ensure_schema()
    store.delete_repo(TEST_REPO)
    yield store
    store.delete_repo(TEST_REPO)
    store.close()
