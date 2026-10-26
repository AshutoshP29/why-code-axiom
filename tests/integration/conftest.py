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
