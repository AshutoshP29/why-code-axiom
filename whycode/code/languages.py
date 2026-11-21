"""Languages the code map reads besides Python: a tree-sitter grammar plus one query each.

Python keeps its own walker in entities.py, which has rules a query does not express simply
(decorators, if/try blocks at module level). Every other language is a QueryLanguage: entities.py
runs its query and turns the matches into entities, so adding a language means adding a grammar
and a query here, nothing else.

Each match of a query captures `@name` and exactly one of:
- @class, @function  a definition; the captured node gives its lines, @name its name. Nesting by
                     line range gives qualified names ("Router.handle", "outer.inner").
- @config            a file-level declaration, the whole statement, with its value as @value. Kept
                     only for UPPER_CASE names whose value is not code (see `code_values`).
- @default           a parameter with a default (@value). Kept only when the default references a
                     constant, and only for the definition the parameter list belongs to.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Query


@dataclass(frozen=True)
class QueryLanguage:
    name: str
    suffixes: frozenset[str]
    language: Language
    query: Query
    # Value node types that make a declaration a function or class rather than config:
    # `const make = () => 1` is a function, `const LIMIT = 5` is config.
    code_values: frozenset[str]
    # Member access node types and the field holding the member's name, so that a default like
    # `timeout = config.TIMEOUT` is seen to reference the constant TIMEOUT.
    member_name_field: dict[str, str]
    # Suffixes of generated files to leave out (minified bundles): one line, thousands of names.
    skipped_suffixes: tuple[str, ...] = ()


_JS_FUNCTION = "[(arrow_function) (function_expression) (generator_function)]"
_JS_DECLARATOR = "(variable_declarator name: (identifier) @name value: (_) @value)"
_JS_DECLARATION = (
    f"[(lexical_declaration {_JS_DECLARATOR}) (variable_declaration {_JS_DECLARATOR})]"
)

# Covers ES modules and CommonJS: `export function f`, `module.exports = { f() {} }`,
# `res.send = function send()`, `const handler = () => {}`, classes and their methods.
JAVASCRIPT_QUERY = f"""
(class_declaration name: (_) @name) @class
(class name: (_) @name) @class
(variable_declarator name: (identifier) @name value: (class !name)) @class

(function_declaration name: (identifier) @name) @function
(generator_function_declaration name: (identifier) @name) @function
(method_definition name: (_) @name) @function
(variable_declarator name: (identifier) @name value: {_JS_FUNCTION}) @function
(assignment_expression
  left: [(identifier) @name (member_expression property: (property_identifier) @name)]
  right: {_JS_FUNCTION}) @function
(pair key: [(property_identifier) (string)] @name value: {_JS_FUNCTION}) @function

(program {_JS_DECLARATION} @config)
(program (export_statement declaration: {_JS_DECLARATION}) @config)

(formal_parameters (assignment_pattern left: (identifier) @name right: (_) @value) @default)
"""


def _javascript() -> QueryLanguage:
    language = Language(tsjs.language())
    return QueryLanguage(
        name="javascript",
        suffixes=frozenset({".js", ".mjs", ".cjs", ".jsx"}),
        language=language,
        query=Query(language, JAVASCRIPT_QUERY),
        code_values=frozenset(
            {"arrow_function", "function_expression", "generator_function", "class"}
        ),
        member_name_field={"member_expression": "property"},
        skipped_suffixes=(".min.js", ".min.mjs", ".min.cjs"),
    )


JAVASCRIPT = _javascript()
QUERY_LANGUAGES = (JAVASCRIPT,)


def language_for(path: str) -> QueryLanguage | None:
    """The query language that reads this file, or None (Python files included: not a query
    language)."""
    p = PurePosixPath(path.replace("\\", "/"))
    for lang in QUERY_LANGUAGES:
        if p.suffix in lang.suffixes and not p.name.endswith(lang.skipped_suffixes):
            return lang
    return None
