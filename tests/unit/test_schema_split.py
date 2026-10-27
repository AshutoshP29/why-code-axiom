from whycode.graph.schema import load_statements, split_statements


def test_real_schema_splits_into_create_statements():
    stmts = load_statements()
    assert len(stmts) == 20  # 11 constraints, 1 vector, 1 fulltext, 7 range indexes
    assert all(s.startswith("CREATE ") for s in stmts)
    assert all("//" not in s and ";" not in s for s in stmts)


def test_real_schema_keeps_vector_and_fulltext_statements_whole():
    stmts = load_statements()
    vector = [s for s in stmts if "VECTOR INDEX" in s]
    fulltext = [s for s in stmts if "FULLTEXT INDEX" in s]
    assert len(vector) == 1 and "`vector.dimensions`: 384" in vector[0]
    assert len(fulltext) == 1 and "n.aliases_text" in fulltext[0]


def test_commented_query_patterns_are_not_run():
    assert not any(s.lstrip().startswith(("MATCH", "CALL", "RETURN")) for s in load_statements())


def test_inline_comment_after_semicolon_dropped():
    text = "CREATE A;   // id = x\nCREATE B; // y"
    assert split_statements(text) == ["CREATE A", "CREATE B"]


def test_comment_inside_statement_dropped():
    assert split_statements("CREATE A // note\n  FOR (n);") == ["CREATE A \n  FOR (n)"]


def test_block_comment_dropped():
    assert split_statements("/* header ; */ CREATE A; /* x */") == ["CREATE A"]


def test_slashes_and_semicolons_inside_strings_kept():
    text = "RETURN 'http://x;y' AS a; RETURN \"//z\" AS b; RETURN `we;ird//name`;"
    assert split_statements(text) == [
        "RETURN 'http://x;y' AS a",
        'RETURN "//z" AS b',
        "RETURN `we;ird//name`",
    ]


def test_escaped_quote_inside_string():
    assert split_statements(r"RETURN 'it\'s; fine'; RETURN 2") == [
        r"RETURN 'it\'s; fine'",
        "RETURN 2",
    ]


def test_last_statement_without_semicolon_kept():
    assert split_statements("CREATE A;\nCREATE B") == ["CREATE A", "CREATE B"]


def test_only_comments_gives_nothing():
    assert split_statements("// a\n// b;\n\n") == []
