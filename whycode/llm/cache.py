"""LLM response cache in Postgres, keyed by sha256(prompt_version + model + input).

A re-run with the same prompt version, model and input is served from here with no API call.
"""

import hashlib

import psycopg

LLM_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS llm_cache (
    key            text        PRIMARY KEY,
    repo           text,
    prompt_version text        NOT NULL,
    provider       text        NOT NULL,
    model          text        NOT NULL,
    response       text        NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
)
"""


def cache_key(prompt_version: str, model: str, prompt_input: str) -> str:
    # Separators keep ("ab", "c") and ("a", "bc") from colliding.
    payload = f"{prompt_version}\x1f{model}\x1f{prompt_input}".encode()
    return hashlib.sha256(payload).hexdigest()


class PgLLMCache:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def ensure_schema(self) -> None:
        self.conn.execute(LLM_CACHE_DDL)

    def get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT response FROM llm_cache WHERE key = %s", (key,)).fetchone()
        return row[0] if row else None

    def put(
        self,
        key: str,
        *,
        response: str,
        provider: str,
        model: str,
        prompt_version: str,
        repo: str | None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO llm_cache (key, repo, prompt_version, provider, model, response) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (key) DO UPDATE SET response = EXCLUDED.response, "
            "provider = EXCLUDED.provider, created_at = now()",
            (key, repo, prompt_version, provider, model, response),
        )

    def delete_repo(self, repo: str) -> int:
        return self.conn.execute("DELETE FROM llm_cache WHERE repo = %s", (repo,)).rowcount
