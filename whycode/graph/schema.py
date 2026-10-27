"""Apply graph/schema.cypher statement by statement and report what exists afterwards."""

from dataclasses import dataclass
from pathlib import Path

from neo4j import Driver

SCHEMA_PATH = Path(__file__).with_name("schema.cypher")


def split_statements(text: str) -> list[str]:
    """Split Cypher into statements, dropping // and /* */ comments.

    Comments and semicolons inside '...', "..." and `...` are kept as text, so a
    quoted "//" or ";" never ends a statement.
    """
    statements: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote != "`" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
        elif c in "'\"`":
            quote = c
            buf.append(c)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif c == ";":
            statements.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(c)
            i += 1
    statements.append("".join(buf))
    return [s.strip() for s in statements if s.strip()]


def load_statements(path: Path = SCHEMA_PATH) -> list[str]:
    return split_statements(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SchemaItem:
    kind: str  # "constraint" or "index"
    name: str
    type: str
    entity: str  # labels or relationship types
    properties: str

    def __str__(self) -> str:
        return f"{self.kind:<10} {self.type:<12} {self.name:<22} {self.entity}({self.properties})"


def apply_schema(driver: Driver, database: str, statements: list[str] | None = None) -> int:
    """Run every statement and return how many ran. All use IF NOT EXISTS, so re-runs are no-ops."""
    statements = load_statements() if statements is None else statements
    with driver.session(database=database) as session:
        for stmt in statements:
            session.run(stmt).consume()
    return len(statements)


def list_schema(driver: Driver, database: str) -> list[SchemaItem]:
    """Constraints and indexes that exist now, sorted for stable comparison."""
    items: list[SchemaItem] = []
    with driver.session(database=database) as session:
        for r in session.run("SHOW CONSTRAINTS YIELD name, type, labelsOrTypes, properties"):
            items.append(
                SchemaItem(
                    "constraint",
                    r["name"],
                    r["type"],
                    "|".join(r["labelsOrTypes"] or []),
                    ", ".join(r["properties"] or []),
                )
            )
        for r in session.run("SHOW INDEXES YIELD name, type, labelsOrTypes, properties"):
            items.append(
                SchemaItem(
                    "index",
                    r["name"],
                    r["type"],
                    "|".join(r["labelsOrTypes"] or []),
                    ", ".join(r["properties"] or []),
                )
            )
    return sorted(items, key=lambda s: (s.kind, s.name))


def count_nodes(driver: Driver, database: str) -> int:
    with driver.session(database=database) as session:
        return session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
