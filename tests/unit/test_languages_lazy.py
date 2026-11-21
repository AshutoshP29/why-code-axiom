"""Grammars and queries are built on first use, not when the parser is imported: building all of
them took about 4 s, which every API cold start would pay."""

import subprocess
import sys

from whycode.code.languages import QUERY_LANGUAGES, language_for


def test_importing_the_api_builds_no_grammar():
    # A fresh interpreter: in this one, other tests have already parsed files.
    code = (
        "import whycode.api.app, whycode.code.languages as L; "
        "print(sum('language' in x.__dict__ or 'query' in x.__dict__ for x in L.QUERY_LANGUAGES))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0"


def test_a_language_is_built_once_and_kept():
    go = language_for("cmd/main.go")
    assert go is not None
    assert go.query is go.query and go.language is go.language


def test_every_grammar_name_resolves():
    for lang in QUERY_LANGUAGES:
        module, function = lang.grammar.split(":")
        assert module.startswith("tree_sitter_") and function.startswith("language"), lang.name
