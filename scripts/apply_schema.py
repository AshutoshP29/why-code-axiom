"""Apply whycode/graph/schema.cypher to a Neo4j target and list the constraints and indexes.

Safe to run twice: every statement is CREATE ... IF NOT EXISTS.

Usage:
    uv run python scripts/apply_schema.py --target test   # local docker container
    uv run python scripts/apply_schema.py --target aura   # real data; refuses a non-empty graph
"""

import argparse
import sys

from whycode.config import ConfigError, get_settings, redact
from whycode.graph.client import aura_target, local_test_target
from whycode.graph.schema import apply_schema, count_nodes, list_schema, load_statements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", choices=["test", "aura"], required=True)
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="apply to Aura even if it already holds nodes (uniqueness constraints can then fail)",
    )
    args = parser.parse_args()

    settings = None
    if args.target == "aura":
        try:
            settings = get_settings()
        except ConfigError as exc:
            print(f"FAIL config: {exc}")
            return 2
        target = aura_target(settings)
    else:
        target = local_test_target()

    statements = load_statements()
    try:
        with target.driver() as driver:
            nodes = count_nodes(driver, target.database)
            print(f"target={target.name} nodes before={nodes}")
            if target.name == "aura" and nodes and not args.allow_nonempty:
                print("Aura is not empty; stopping. Re-run with --allow-nonempty to apply anyway.")
                return 3
            ran = apply_schema(driver, target.database, statements)
            print(f"ran {ran} statements")
            items = list_schema(driver, target.database)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print("FAIL " + (redact(msg, settings) if settings else msg))
        if target.name == "aura":
            print("The free Aura instance may be paused: resume it at console.neo4j.io")
        return 1

    constraints = [i for i in items if i.kind == "constraint"]
    indexes = [i for i in items if i.kind == "index"]
    print(f"\n{len(constraints)} constraints, {len(indexes)} indexes now exist:")
    for item in items:
        print("  " + str(item))
    return 0


if __name__ == "__main__":
    sys.exit(main())
