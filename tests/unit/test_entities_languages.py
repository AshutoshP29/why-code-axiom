"""The languages read through queries besides JavaScript (test_entities_javascript.py):
TypeScript, Java, Go, C#, Rust, Ruby and PHP. Each sample has its classes, functions and
constants in the shapes that language writes them."""

import pytest

from tests.gitrepo import _git, _write
from whycode.code.entities import EntityKind, is_supported, parse_file
from whycode.code.languages import QUERY_LANGUAGES, language_for
from whycode.ingest import codemap

REPO = "o/r"

TYPESCRIPT = """\
export const DEFAULT_TIMEOUT = 30;
export interface Options { retries: number; serve(x: number): void }
export enum Mode { A, B }
export abstract class Base { abstract run(): void }
export class Router extends Base {
  static LIMIT = 5;
  constructor(opts: Options = DEFAULT_OPTS) { super(); }
  handle = (req: Request, timeout = config.TIMEOUT): void => {};
}
export function main(retries: number = MAX_RETRIES, flag?: boolean): void {}
namespace Utils { export function inner() {} }
declare function ext(a: string): void;
"""

JAVA = """\
package com.example;
public class Router extends Base {
    public static final int MAX_RETRIES = 3;
    static final String DEFAULT_NAME = "x", OTHER_NAME = "y";
    private int count = 0;
    private static final Logger log = Logger.get();
    public Router(Options opts) { }
    public void handle(Request req) { }
    interface Callback { int LIMIT = 5; void call(); }
    enum Mode { A; void m() {} }
    record Point(int x, int y) { }
}
"""

GO = """\
package router
const DefaultTimeout = 30
const (
\tMaxRetries = 3
\t_ = 9
)
var mutable = 1
type Router struct { name string }
type Handler interface { Serve() }
func (r *Router) Handle(req *Request) error { return nil }
func (Router) Name() string { return "" }
func New(opts Options) *Router { return nil }
"""

CSHARP = """\
namespace App.Web;
public class Router : Base {
  public const int MaxRetries = 3;
  private static readonly TimeSpan DefaultTimeout = TimeSpan.FromSeconds(30);
  private int count;
  public Router(Options opts) { }
  public void Handle(Request req, int retries = MaxRetries, string name = "x") { }
  public int Size { get; set; }
  interface IHandler { void Serve(); }
  struct Point { }
  enum Mode { A }
  record Pair(int A, int B);
}
"""

RUST = """\
pub const MAX_RETRIES: u32 = 3;
static DEFAULT_NAME: &str = "x";
pub struct Router { name: String }
pub enum Mode { A }
pub trait Handler { fn serve(&self); }
impl Router { const LIMIT: u32 = 5; pub fn new() -> Self { todo!() } }
impl Handler for Router { fn serve(&self) {} }
mod inner { pub fn run() {} }
"""

RUBY = """\
module Rack
  class Router < Base
    MAX_RETRIES = 3
    HANDLER = ->(x) { x }
    def initialize(opts = DEFAULT_OPTS, timeout: Config::TIMEOUT, verbose: false)
    end
    def self.create; end
  end
end
"""

PHP = """\
<?php
namespace App;
const MAX_RETRIES = 3;
class Router extends Base {
    public const TIMEOUT = 30;
    public function __construct($opts = self::DEFAULTS, int $retries = MAX_RETRIES) {}
    public static function create() {}
}
interface Handler { public function serve(); }
trait Loggable { function log() {} }
enum Mode { case A; }
function helper($x = 1) {}
"""

# path, source, {qualified name: parent's qualified name ("" for the file)} for classes and
# functions, and {qualified name: value} for config keys.
CASES = {
    "typescript": (
        "src/router.ts",
        TYPESCRIPT,
        {
            "Options": "",
            "Options.serve": "Options",
            "Mode": "",
            "Base": "",
            "Base.run": "Base",
            "Router": "",
            "Router.constructor": "Router",
            "Router.handle": "Router",
            "main": "",
            "Utils.inner": "",  # a namespace names its contents but is no entity
            "ext": "",
        },
        {
            "DEFAULT_TIMEOUT": "30",
            "Router.constructor.opts": "DEFAULT_OPTS",
            "Router.handle.timeout": "config.TIMEOUT",
            "main.retries": "MAX_RETRIES",
        },
    ),
    "java": (
        "src/main/java/com/example/Router.java",
        JAVA,
        {
            "Router": "",
            "Router.Router": "Router",
            "Router.handle": "Router",
            "Router.Callback": "Router",
            "Router.Callback.call": "Router.Callback",
            "Router.Mode": "Router",
            "Router.Mode.m": "Router.Mode",
            "Router.Point": "Router",
        },
        {
            "Router.MAX_RETRIES": "3",
            "Router.DEFAULT_NAME": '"x"',
            "Router.OTHER_NAME": '"y"',
            "Router.Callback.LIMIT": "5",  # interface fields are static final
        },
    ),
    "go": (
        "router/router.go",
        GO,
        {
            "Router": "",
            "Handler": "",
            "Handler.Serve": "Handler",
            "Router.Handle": "Router",  # the receiver names the type it belongs to
            "Router.Name": "Router",
            "New": "",
        },
        {"DefaultTimeout": "30", "MaxRetries": "3"},
    ),
    "csharp": (
        "src/App/Router.cs",
        CSHARP,
        {
            "Router": "",
            "Router.Router": "Router",
            "Router.Handle": "Router",
            "Router.Size": "Router",
            "Router.IHandler": "Router",
            "Router.IHandler.Serve": "Router.IHandler",
            "Router.Point": "Router",
            "Router.Mode": "Router",
            "Router.Pair": "Router",
        },
        {
            "Router.MaxRetries": "3",
            "Router.DefaultTimeout": "TimeSpan.FromSeconds(30)",
            "Router.Handle.retries": "MaxRetries",
        },
    ),
    "rust": (
        "src/router.rs",
        RUST,
        {
            "Router": "",
            "Mode": "",
            "Handler": "",
            "Handler.serve": "Handler",
            "Router.new": "Router",  # an impl block names its functions after the type
            "Router.serve": "Router",
            "inner.run": "",
        },
        {"MAX_RETRIES": "3", "DEFAULT_NAME": '"x"', "Router.LIMIT": "5"},
    ),
    "ruby": (
        "lib/rack/router.rb",
        RUBY,
        {
            "Rack": "",
            "Rack.Router": "Rack",
            "Rack.Router.initialize": "Rack.Router",
            "Rack.Router.create": "Rack.Router",
        },
        {
            "Rack.Router.MAX_RETRIES": "3",
            "Rack.Router.initialize.opts": "DEFAULT_OPTS",
            "Rack.Router.initialize.timeout": "Config::TIMEOUT",
        },
    ),
    "php": (
        "src/Router.php",
        PHP,
        {
            "Router": "",
            "Router.__construct": "Router",
            "Router.create": "Router",
            "Handler": "",
            "Handler.serve": "Handler",
            "Loggable": "",
            "Loggable.log": "Loggable",
            "Mode": "",
            "helper": "",
        },
        {
            "MAX_RETRIES": "3",
            "Router.TIMEOUT": "30",
            "Router.__construct.opts": "self::DEFAULTS",
            "Router.__construct.retries": "MAX_RETRIES",
        },
    ),
}


def _qualified_by_id(parsed) -> dict[str, str]:
    return {e.id: e.qualified_name for e in parsed.entities[1:]} | {parsed.entities[0].id: ""}


@pytest.mark.parametrize("language", sorted(CASES))
def test_classes_and_functions_nest_under_their_parents(language):
    path, source, code, _ = CASES[language]
    parsed = parse_file(REPO, path, source)
    assert not parsed.has_syntax_errors
    names = _qualified_by_id(parsed)
    found = {
        e.qualified_name: names[e.parent_id]
        for e in parsed.entities[1:]
        if e.kind in (EntityKind.CLASS, EntityKind.FUNCTION)
    }
    assert found == code


@pytest.mark.parametrize("language", sorted(CASES))
def test_constants_and_defaults_that_reference_them_are_config(language):
    path, source, _, config = CASES[language]
    parsed = parse_file(REPO, path, source)
    found = {e.qualified_name: e.value for e in parsed.of_kind(EntityKind.CONFIG_KEY)}
    assert found == config


@pytest.mark.parametrize("language", sorted(CASES))
def test_ids_are_unique_and_parsing_is_deterministic(language):
    path, source, _, _ = CASES[language]
    parsed = parse_file(REPO, path, source)
    ids = [e.id for e in parsed.entities]
    assert len(ids) == len(set(ids))
    assert parse_file(REPO, path, source) == parsed


def test_kinds_and_ids_follow_the_graph_schema():
    parsed = parse_file(REPO, "router/router.go", GO)
    by_name = {e.qualified_name: e for e in parsed.entities}
    assert by_name["Router"].id == "o/r#cls:router/router.go::Router"
    assert by_name["Router.Handle"].id == "o/r#fn:router/router.go::Router.Handle"
    assert by_name["MaxRetries"].id == "o/r#cfg:MaxRetries"
    assert (by_name["Router.Handle"].start_line, by_name["Router.Handle"].end_line) == (10, 10)


def test_rust_impl_methods_belong_to_the_type_even_without_it_in_the_file():
    parsed = parse_file(REPO, "src/ext.rs", "impl Router { fn extra(&self) {} }\n")
    [fn] = parsed.of_kind(EntityKind.FUNCTION)
    assert (fn.qualified_name, fn.parent_id) == ("Router.extra", parsed.entities[0].id)


def test_what_is_not_config():
    names = lambda source, path: {  # noqa: E731
        e.name for e in parse_file(REPO, path, source).of_kind(EntityKind.CONFIG_KEY)
    }
    # Java: a lowercase static final and a field that is not static final.
    assert not names(JAVA, "A.java") & {"log", "count"}
    # Go: `var`, and the blank identifier.
    assert not names(GO, "a.go") & {"mutable", "_"}
    # C#: a field without a value, and a literal default.
    assert not names(CSHARP, "A.cs") & {"count", "name"}
    # Ruby: a lambda is code, a literal keyword default is not a constant.
    assert not names(RUBY, "a.rb") & {"HANDLER", "verbose"}
    # PHP: a literal default.
    assert "x" not in names(PHP, "a.php")
    # TypeScript: a class field.
    assert "LIMIT" not in names(TYPESCRIPT, "a.ts")


def test_tsx_files_use_the_tsx_grammar():
    src = "export const App = ({ n = LIMIT }) => <div onClick={() => go()}>{n}</div>;\n"
    parsed = parse_file(REPO, "src/App.tsx", src)
    assert not parsed.has_syntax_errors
    assert [e.qualified_name for e in parsed.of_kind(EntityKind.FUNCTION)] == ["App"]


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("a.ts", "typescript"),
        ("a.mts", "typescript"),
        ("a.tsx", "tsx"),
        ("A.java", "java"),
        ("a.go", "go"),
        ("A.cs", "csharp"),
        ("a.rs", "rust"),
        ("a.rb", "ruby"),
        ("a.php", "php"),
        ("lib\\a.js", "javascript"),
    ],
)
def test_each_suffix_reads_with_its_language(path, language):
    assert language_for(path).name == language
    assert is_supported(path)


@pytest.mark.parametrize("path", ["api/v1/user.pb.go", "Form1.Designer.cs", "Gen.g.cs", "a.kt"])
def test_generated_files_and_other_languages_are_left_out(path):
    assert not is_supported(path)


def test_every_language_has_a_working_query():
    for lang in QUERY_LANGUAGES:
        assert lang.query.pattern_count > 0, lang.name
        assert lang.suffixes, lang.name


def test_the_code_map_reads_every_language(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    for _, (path, source, _, _) in CASES.items():
        _write(root, path, source)
    _write(root, "api/user.pb.go", "package api\nfunc Generated() {}\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "many languages")
    assert codemap.code_files(root) == sorted(path for path, *_ in CASES.values())
    b = codemap.build_code_map(REPO, root)
    assert "o/r#fn:router/router.go::Router.Handle" in b.nodes["Function"]
    assert "o/r#cls:src/main/java/com/example/Router.java::Router" in b.nodes["Class"]
    assert "o/r#cfg:MaxRetries" in b.nodes["ConfigKey"]
