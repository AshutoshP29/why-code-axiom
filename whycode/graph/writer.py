"""Write a GraphBatch to Neo4j: MERGE only, in one transaction.

Nodes are MERGEd on `id` (unique per label, see schema.cypher) and their properties updated;
relationships are MERGEd between existing nodes. Writing the same batch twice changes nothing.
Before a source's decisions are written, its old ones are DETACH DELETEd, so re-extracting a
pull request replaces its decisions instead of adding more (schema rule 5).
"""

from dataclasses import dataclass

from neo4j import Driver, ManagedTransaction

from whycode.graph.build import NODE_LABELS, REL_TYPES, GraphBatch


@dataclass(frozen=True)
class WriteStats:
    nodes: int
    relationships: int
    decisions_replaced: int


def _check(label: str, kinds: frozenset[str]) -> str:
    # Labels and types cannot be query parameters; only allowlisted names reach the Cypher text.
    if label not in kinds:
        raise ValueError(f"not allowed in Cypher: {label!r}")
    return label


def _write(tx: ManagedTransaction, batch: GraphBatch) -> WriteStats:
    replaced = 0
    for label, source_id in batch.replaces_decisions_of:
        res = tx.run(
            f"MATCH (d:Decision {{repo: $repo}})-[:DECIDED_IN]->(:{_check(label, NODE_LABELS)} "
            "{id: $id, repo: $repo}) DETACH DELETE d RETURN count(d) AS n",
            repo=batch.repo,
            id=source_id,
        )
        replaced += res.single()["n"]
    for label, nodes in batch.nodes.items():
        tx.run(
            f"UNWIND $rows AS row MERGE (n:{_check(label, NODE_LABELS)} {{id: row.id}}) "
            "SET n += row.props",
            rows=[{"id": id_, "props": props} for id_, props in nodes.items()],
        ).consume()
    for (type_, from_label, to_label), pairs in batch.rels.items():
        tx.run(
            f"UNWIND $rows AS row "
            f"MATCH (a:{_check(from_label, NODE_LABELS)} {{id: row.a}}) "
            f"MATCH (b:{_check(to_label, NODE_LABELS)} {{id: row.b}}) "
            f"MERGE (a)-[r:{_check(type_, REL_TYPES)}]->(b) SET r += row.props",
            rows=[{"a": a, "b": b, "props": props} for (a, b), props in pairs.items()],
        ).consume()
    nodes, rels = batch.count()
    return WriteStats(nodes, rels, replaced)


def write_batch(driver: Driver, database: str, batch: GraphBatch) -> WriteStats:
    with driver.session(database=database) as session:
        return session.execute_write(_write, batch)


def repo_counts(driver: Driver, database: str, repo: str) -> tuple[dict[str, int], int]:
    """(nodes per label, relationships) for one repo; both ends of a relationship are in it."""
    with driver.session(database=database) as session:
        by_label = {
            r["label"]: r["n"]
            for r in session.run(
                "MATCH (n {repo: $repo}) UNWIND labels(n) AS label "
                "RETURN label, count(*) AS n ORDER BY label",
                repo=repo,
            )
        }
        rels = session.run(
            "MATCH (a {repo: $repo})-[r]->(b {repo: $repo}) RETURN count(r) AS n", repo=repo
        ).single()["n"]
    return by_label, rels


def delete_repo(driver: Driver, database: str, repo: str) -> int:
    """Remove every node of one repo (schema section 6)."""
    with driver.session(database=database) as session:
        return session.run(
            "MATCH (n {repo: $repo}) DETACH DELETE n RETURN count(n) AS n", repo=repo
        ).single()["n"]
