from whycode.graph.client import Neo4jTarget


def test_password_not_in_repr():
    t = Neo4jTarget("aura", "neo4j+s://h", "u", "fake-secret-pw", "db")
    assert "fake-secret-pw" not in repr(t)
