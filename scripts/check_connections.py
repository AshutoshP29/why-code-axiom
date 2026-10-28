"""Check every external service and print OK or FAIL per service. Never prints secret values.

Usage:
    uv run python scripts/check_connections.py                # 1 tiny call per LLM
    uv run python scripts/check_connections.py --no-llm-call  # list models only, no calls
"""

import argparse
import sys
from collections.abc import Callable
from typing import NoReturn

import httpx
import psycopg

from whycode.config import ConfigError, Settings, get_settings, redact
from whycode.graph.client import aura_target, local_test_target

Check = Callable[[Settings], list[str]]  # returns detail lines; raises on failure


def check_neo4j_aura(s: Settings) -> list[str]:
    target = aura_target(s)
    try:
        with target.driver() as driver:
            driver.verify_connectivity()
            with driver.session(database=target.database) as session:
                session.run("RETURN 1").consume()
    except Exception as exc:
        raise RuntimeError(
            f"{exc}\n    The free Aura instance may be paused: resume it at console.neo4j.io"
        ) from None
    return ["RETURN 1 ok"]


def check_neo4j_test(s: Settings) -> list[str]:
    target = local_test_target()
    try:
        with target.driver() as driver, driver.session(database=target.database) as session:
            session.run("RETURN 1").consume()
    except Exception as exc:
        raise RuntimeError(f"{exc}\n    Start it with: docker compose up -d") from None
    return [f"RETURN 1 ok ({target.uri})"]


def check_postgres(s: Settings) -> list[str]:
    try:
        with psycopg.connect(s.postgres_dsn.get_secret_value(), connect_timeout=5) as conn:
            conn.execute("SELECT 1").fetchone()
            version = conn.execute("SHOW server_version").fetchone()[0]
    except Exception as exc:
        raise RuntimeError(f"{exc}\n    Start it with: docker compose up -d") from None
    return [f"SELECT 1 ok (server {version})"]


def check_github(s: Settings) -> list[str]:
    resp = httpx.get(
        "https://api.github.com/rate_limit",
        headers={
            "Authorization": f"Bearer {s.github_token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    resp.raise_for_status()
    core = resp.json()["resources"]["core"]
    if core["limit"] <= 60:
        raise RuntimeError("token not accepted: got the unauthenticated limit of 60/hour")
    return [f"core rate limit {core['remaining']}/{core['limit']} remaining"]


def _fail(lines: list[str], reason: str) -> NoReturn:
    """Fail a check but keep the detail gathered so far (e.g. the model list) in the output."""
    raise RuntimeError("\n".join([*lines, reason])) from None


def check_gemini(s: Settings, call: bool) -> list[str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=s.gemini_api_key.get_secret_value())
    models = sorted(
        m.name.removeprefix("models/")
        for m in client.models.list()
        if "generateContent" in (m.supported_actions or [])
    )
    lines = [f"{len(models)} models support generateContent:"]
    lines += [f"  {'*' if m == s.gemini_model else ' '} {m}" for m in models]
    if s.gemini_model not in models:
        _fail(lines, f"GEMINI_MODEL={s.gemini_model} is not in the list")
    if call:
        # Being listed does not mean usable: retired models still list but 404 on generate.
        # No thinking config: it differs across Gemini generations; this call only proves access.
        try:
            resp = client.models.generate_content(
                model=s.gemini_model,
                contents="Reply with the single word OK.",
                config=types.GenerateContentConfig(max_output_tokens=64),
            )
        except Exception as exc:
            _fail(lines, f"tiny call to {s.gemini_model} failed: {exc}")
        lines.append(f"tiny call to {s.gemini_model}: replied {(resp.text or '').strip()!r}")
    return lines


def check_groq(s: Settings, call: bool) -> list[str]:
    from groq import Groq

    client = Groq(api_key=s.groq_api_key.get_secret_value(), timeout=30)
    data = client.models.list().data
    models = sorted(m.id for m in data if getattr(m, "active", True))
    lines = [f"{len(models)} active models:"]
    lines += [f"  {'*' if m == s.groq_model else ' '} {m}" for m in models]
    if s.groq_model not in models:
        _fail(lines, f"GROQ_MODEL={s.groq_model} is not in the list")
    if call:
        # 64 tokens, not 5: reasoning models spend tokens before answering.
        try:
            resp = client.chat.completions.create(
                model=s.groq_model,
                messages=[{"role": "user", "content": "Reply with the single word OK."}],
                max_tokens=64,
            )
        except Exception as exc:
            _fail(lines, f"tiny call to {s.groq_model} failed: {exc}")
        reply = (resp.choices[0].message.content or "").strip()
        lines.append(f"tiny call to {s.groq_model}: replied {reply!r}")
    return lines


def check_local(s: Settings, call: bool) -> list[str]:
    if not s.local_llm_model:
        return ["not configured (LOCAL_LLM_MODEL is empty)"]
    from whycode.llm.providers import LocalProvider

    try:
        tags = httpx.get(f"{s.local_llm_url}/api/tags", timeout=10).json()
    except Exception as exc:
        raise RuntimeError(
            f"{exc}\n    Start Ollama (open the app, or run: ollama serve)"
        ) from None
    models = sorted(m["name"] for m in tags.get("models", []))
    lines = [f"{len(models)} local models:"]
    lines += [f"  {'*' if m == s.local_llm_model else ' '} {m}" for m in models]
    if s.local_llm_model not in models:
        _fail(
            lines,
            f"LOCAL_LLM_MODEL={s.local_llm_model} is not pulled: ollama pull {s.local_llm_model}",
        )
    if call:
        try:
            reply = LocalProvider(s.local_llm_model, s.local_llm_url).complete_json(
                "Reply in JSON.", 'Return exactly {"ok": true}'
            )
        except Exception as exc:
            _fail(lines, f"tiny call to {s.local_llm_model} failed: {exc}")
        lines.append(f"tiny call to {s.local_llm_model}: replied {reply.strip()!r} (free)")
    return lines


def run(settings: Settings, call_llms: bool) -> bool:
    checks: list[tuple[str, Check]] = [
        ("Neo4j Aura", check_neo4j_aura),
        ("Neo4j test container", check_neo4j_test),
        ("Postgres", check_postgres),
        ("GitHub", check_github),
        ("Gemini", lambda s: check_gemini(s, call_llms)),
        ("Groq", lambda s: check_groq(s, call_llms)),
        ("Local model", lambda s: check_local(s, call_llms)),
    ]
    all_ok = True
    for name, check in checks:
        try:
            lines, status = check(settings), "OK"
        except Exception as exc:
            lines, status, all_ok = [f"{type(exc).__name__}: {exc}"], "FAIL", False
        print(f"[{status:>4}] {name}")
        for line in lines:
            print("       " + redact(line, settings).replace("\n", "\n       "))
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-llm-call", action="store_true", help="list models only; make no generation calls"
    )
    args = parser.parse_args()
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"[FAIL] config: {exc}")
        return 2
    return 0 if run(settings, call_llms=not args.no_llm_call) else 1


if __name__ == "__main__":
    sys.exit(main())
