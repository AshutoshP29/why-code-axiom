import ssl

from whycode.graph.client import Neo4jTarget, tls_args


def test_secure_scheme_rewritten_with_verifying_context():
    uri, extra = tls_args("neo4j+s://abc.databases.neo4j.io")
    assert uri == "neo4j://abc.databases.neo4j.io"
    ctx = extra["ssl_context"]
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_bolt_secure_scheme_also_handled():
    uri, extra = tls_args("bolt+s://host:7687")
    assert uri == "bolt://host:7687" and "ssl_context" in extra


def test_plain_scheme_untouched():
    assert tls_args("bolt://localhost:7688") == ("bolt://localhost:7688", {})


def test_self_signed_scheme_left_to_driver():
    assert tls_args("neo4j+ssc://host") == ("neo4j+ssc://host", {})


def test_password_not_in_repr():
    t = Neo4jTarget("aura", "neo4j+s://h", "u", "fake-secret-pw", "db")
    assert "fake-secret-pw" not in repr(t)
