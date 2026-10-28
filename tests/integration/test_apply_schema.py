from whycode.graph.schema import apply_schema, list_schema, load_statements

EXPECTED_CONSTRAINTS = {
    "repo_id", "commit_id", "pr_id", "issue_id", "decision_id", "evidence_id",
    "person_id", "file_id", "function_id", "module_id", "config_id", "class_id",
}  # fmt: skip
EXPECTED_INDEXES = {
    "evidence_embedding", "entity_search", "decision_repo_status", "decision_date",
    "commit_repo_date", "pr_repo_number", "issue_repo_number", "file_repo", "person_repo",
}  # fmt: skip


def test_apply_schema_is_idempotent(neo4j_test):
    driver, db = neo4j_test
    assert apply_schema(driver, db) == len(load_statements())
    first = list_schema(driver, db)
    apply_schema(driver, db)  # second run must not raise
    assert list_schema(driver, db) == first


def test_all_constraints_and_indexes_exist(neo4j_test):
    driver, db = neo4j_test
    apply_schema(driver, db)
    items = list_schema(driver, db)
    constraints = {i.name for i in items if i.kind == "constraint"}
    indexes = {i.name: i for i in items if i.kind == "index"}
    assert constraints >= EXPECTED_CONSTRAINTS
    assert set(indexes) >= EXPECTED_INDEXES
    assert indexes["evidence_embedding"].type == "VECTOR"
    assert indexes["entity_search"].type == "FULLTEXT"
    assert indexes["entity_search"].entity == "File|Class|Function|Module|ConfigKey"
    assert "entity_names" not in indexes  # the pre-v4 index is gone


def test_upgrade_from_v3_replaces_the_old_fulltext_index(neo4j_test):
    driver, db = neo4j_test
    with driver.session(database=db) as s:
        s.run("DROP INDEX entity_search IF EXISTS").consume()
        s.run(
            "CREATE FULLTEXT INDEX entity_names IF NOT EXISTS "
            "FOR (n:File|Function|Module|ConfigKey) "
            "ON EACH [n.name, n.qualified_name, n.aliases_text]"
        ).consume()
    apply_schema(driver, db)
    names = {i.name for i in list_schema(driver, db) if i.kind == "index"}
    assert "entity_search" in names and "entity_names" not in names
