import pytest

from tests.gitrepo import _git, _write
from whycode.code.diff import entities_changed
from whycode.code.entities import EntityKind, UnsupportedFileError, is_supported, parse_file
from whycode.ingest import codemap

REPO = "o/r"
PATH = "lib/router.js"

# Line numbers matter: tests below assert them.
ROUTER = """\
'use strict';
const DEFAULT_TIMEOUT = 30, MAX_RETRIES = 3;
var legacy = 1;
export const API_URL = "https://x";
const make = () => 1;
const Widget = class { render() {} };

class Router extends Base {
  static LIMIT = 5;

  constructor(opts = DEFAULT_OPTS) {
    super();
    this.handler = () => {};
  }

  get size() { return 1 }
  set size(v) {}
  [Symbol.iterator]() {}
  #hide() {}
}

res.send = function send(body, timeout = config.TIMEOUT) {
  return body;
};

module.exports = {
  listen() {},
  close: function () {},
  'quoted-key': () => {},
};

function outer(items) {
  items.map((x = LIMIT) => x);
  function inner() {}
}

export default function main(retries = MAX_RETRIES, flag = false) {}
"""


@pytest.fixture(scope="module")
def parsed():
    return parse_file(REPO, PATH, ROUTER)


def by_qualified(p, kind):
    return {e.qualified_name: e for e in p.of_kind(kind)}


def lines(e):
    return (e.start_line, e.end_line)


def test_file_entity_comes_first_and_spans_the_file(parsed):
    f = parsed.entities[0]
    assert (f.kind, f.id, f.name, lines(f)) == (
        EntityKind.FILE,
        "o/r#file:lib/router.js",
        "router.js",
        (1, 37),
    )
    assert not parsed.has_syntax_errors


def test_classes_including_a_class_assigned_to_a_name(parsed):
    classes = by_qualified(parsed, EntityKind.CLASS)
    assert {q: lines(e) for q, e in classes.items()} == {"Widget": (6, 6), "Router": (8, 20)}
    assert classes["Router"].id == "o/r#cls:lib/router.js::Router"


def test_functions_methods_and_functions_assigned_to_names(parsed):
    fns = by_qualified(parsed, EntityKind.FUNCTION)
    assert set(fns) == {
        "make",
        "Widget.render",
        "Router.constructor",
        "Router.constructor.handler",
        "Router.size",
        "Router.[Symbol.iterator]",
        "Router.#hide",
        "send",  # res.send = function send() {...}: one entity, not send.send
        "listen",
        "close",
        "quoted-key",  # the quotes are not part of the name
        "outer",
        "outer.inner",
        "main",
    }
    assert lines(fns["Router.constructor"]) == (11, 14)
    assert lines(fns["send"]) == (22, 24)
    assert fns["Router.constructor"].id == "o/r#fn:lib/router.js::Router.constructor"


def test_a_getter_and_its_setter_are_one_entity_that_keeps_the_first(parsed):
    sizes = [e for e in parsed.entities if e.qualified_name == "Router.size"]
    assert [lines(e) for e in sizes] == [(16, 16)]


def test_parents_are_the_innermost_definition_around_each(parsed):
    fns = by_qualified(parsed, EntityKind.FUNCTION)
    file_id = parsed.entities[0].id
    assert fns["Router.constructor"].parent_id == "o/r#cls:lib/router.js::Router"
    assert fns["Router.constructor.handler"].parent_id == fns["Router.constructor"].id
    assert fns["outer.inner"].parent_id == fns["outer"].id
    assert fns["send"].parent_id == file_id
    assert fns["listen"].parent_id == file_id


def test_config_keys_are_top_level_constants_and_defaults_that_reference_one(parsed):
    config = by_qualified(parsed, EntityKind.CONFIG_KEY)
    assert {q: e.value for q, e in config.items()} == {
        "DEFAULT_TIMEOUT": "30",
        "MAX_RETRIES": "3",
        "API_URL": '"https://x"',
        "Router.constructor.opts": "DEFAULT_OPTS",
        "send.timeout": "config.TIMEOUT",
        "main.retries": "MAX_RETRIES",
    }
    assert lines(config["DEFAULT_TIMEOUT"]) == (2, 2)
    assert config["DEFAULT_TIMEOUT"].id == "o/r#cfg:DEFAULT_TIMEOUT"
    assert config["DEFAULT_TIMEOUT"].parent_id == parsed.entities[0].id
    assert config["send.timeout"].parent_id == by_qualified(parsed, EntityKind.FUNCTION)["send"].id


def test_not_config_lowercase_class_fields_code_values_literals_and_callback_defaults(parsed):
    names = {e.name for e in parsed.of_kind(EntityKind.CONFIG_KEY)}
    # legacy: lowercase. LIMIT: a class field. make, Widget: a function and a class.
    # flag: a literal default. x: the default of a callback inside outer, not outer's own.
    assert not names & {"legacy", "LIMIT", "make", "Widget", "flag", "x"}


def test_only_config_keys_carry_a_value(parsed):
    assert all((e.value is not None) == (e.kind is EntityKind.CONFIG_KEY) for e in parsed.entities)


def test_config_value_leaves_out_comments():
    src = "const RETRY_CODES = [\n  500, // server error\n  503,\n];\n"
    (cfg,) = parse_file(REPO, "a.js", src).of_kind(EntityKind.CONFIG_KEY)
    assert (cfg.value, lines(cfg)) == ("[ 500, 503, ]", (1, 4))


def test_ids_are_unique_and_parsing_is_deterministic(parsed):
    ids = [e.id for e in parsed.entities]
    assert len(ids) == len(set(ids))
    assert parse_file(REPO, PATH, ROUTER) == parsed


def test_entities_are_in_source_order_outer_first(parsed):
    order = [e.qualified_name for e in parsed.entities[1:]]
    assert order.index("Router") < order.index("Router.constructor")
    assert order.index("Router.constructor") < order.index("Router.constructor.opts")
    assert order.index("Router.constructor.opts") < order.index("Router.constructor.handler")
    assert order.index("outer") < order.index("outer.inner") < order.index("main")


def test_jsx_and_module_files_are_read():
    jsx = parse_file(REPO, "src/App.jsx", "const App = () => <div onClick={() => go()}>hi</div>;\n")
    assert [e.qualified_name for e in jsx.of_kind(EntityKind.FUNCTION)] == ["App"]
    assert not jsx.has_syntax_errors
    for path in ("lib/a.mjs", "lib/a.cjs", "lib/a.js", "src/App.jsx"):
        assert is_supported(path)


@pytest.mark.parametrize("path", ["dist/app.min.js", "src/a.clj", "src/a.erl", "a.json"])
def test_minified_bundles_and_unread_languages_are_not_read(path):
    assert not is_supported(path)
    with pytest.raises(UnsupportedFileError):
        parse_file(REPO, path, "const A = 1;")


def test_syntax_error_keeps_what_was_recovered():
    p = parse_file(REPO, "a.js", "function ok() { return 1 }\nclass {{{\n")
    assert p.has_syntax_errors
    assert "ok" in by_qualified(p, EntityKind.FUNCTION)


def test_empty_file_gives_only_the_file_entity():
    p = parse_file(REPO, "a.js", "")
    assert [(e.kind, lines(e)) for e in p.entities] == [(EntityKind.FILE, (1, 1))]


def test_a_changed_line_counts_for_the_innermost_function(parsed):
    patch = (
        "@@ -11,4 +11,4 @@ class Router extends Base {\n"
        "   constructor(opts = DEFAULT_OPTS) {\n"
        "-    super(opts);\n"
        "+    super();\n"
        "     this.handler = () => {};\n"
        "   }\n"
    )
    changes = entities_changed(parsed, patch)
    assert [(c.entity.qualified_name, c.added, c.removed) for c in changes] == [
        ("Router.constructor", 1, 1)
    ]


def test_code_map_reads_javascript_and_leaves_out_minified_bundles(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, "lib/router.js", ROUTER)
    _write(root, "dist/app.min.js", "function a(){}function b(){}\n")
    _write(root, "src/types.ts", "export const A = 1;\n")
    _write(root, "tool.py", "def f():\n    return 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "mixed")
    assert codemap.code_files(root) == ["lib/router.js", "src/types.ts", "tool.py"]
    b = codemap.build_code_map(REPO, root)
    assert "o/r#fn:lib/router.js::Router.constructor" in b.nodes["Function"]
    assert "o/r#fn:tool.py::f" in b.nodes["Function"]
    assert b.nodes["ConfigKey"]["o/r#cfg:DEFAULT_TIMEOUT"]["path"] == "lib/router.js"
