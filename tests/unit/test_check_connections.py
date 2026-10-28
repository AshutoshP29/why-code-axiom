import importlib.util
from pathlib import Path

from whycode.config import load_settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_connections.py"
spec = importlib.util.spec_from_file_location("check_connections", SCRIPT)
check_connections = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_connections)

SECRET = "fake-secret-zz9"


def _settings(monkeypatch):
    for name, value in {
        "NEO4J_URI": "neo4j+s://h",
        "NEO4J_USERNAME": "u",
        "NEO4J_PASSWORD": SECRET,
        "NEO4J_DATABASE": "d",
        "GEMINI_API_KEY": "g",
        "GROQ_API_KEY": "q",
        "GEMINI_MODEL": "gm",
        "GROQ_MODEL": "qm",
        "LLM_MAX_CALLS": "1",
        "GITHUB_TOKEN": "t",
        "POSTGRES_DSN": "p",
    }.items():
        monkeypatch.setenv(name, value)
    return load_settings(_env_file=None)


def test_failure_is_reported_and_secret_redacted(monkeypatch, capsys):
    s = _settings(monkeypatch)

    def leaky(_):
        raise RuntimeError(f"auth failed for password {SECRET}")

    for fn in ("check_neo4j_aura", "check_neo4j_test", "check_postgres", "check_github"):
        monkeypatch.setattr(check_connections, fn, leaky)
    monkeypatch.setattr(check_connections, "check_gemini", lambda s, call: ["ok"])
    monkeypatch.setattr(check_connections, "check_groq", lambda s, call: ["ok"])

    assert check_connections.run(s, call_llms=False) is False
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "[FAIL] Neo4j Aura" in out and "***" in out
    assert "[  OK] Gemini" in out


def test_all_ok_returns_true(monkeypatch, capsys):
    s = _settings(monkeypatch)
    for fn in ("check_neo4j_aura", "check_neo4j_test", "check_postgres", "check_github"):
        monkeypatch.setattr(check_connections, fn, lambda _: ["fine"])
    monkeypatch.setattr(check_connections, "check_gemini", lambda s, call: ["fine"])
    monkeypatch.setattr(check_connections, "check_groq", lambda s, call: ["fine"])
    assert check_connections.run(s, call_llms=False) is True
    assert "FAIL" not in capsys.readouterr().out


def test_local_model_not_configured_needs_no_network(monkeypatch):
    s = _settings(monkeypatch)
    monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
    assert check_connections.check_local(s, call=True) == [
        "not configured (LOCAL_LLM_MODEL is empty)"
    ]
