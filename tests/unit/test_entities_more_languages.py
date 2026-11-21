"""Kotlin, Swift, Scala, Dart, Bash, Lua, Elixir, Haskell, Objective-C, Julia, Zig and OCaml, read
through their queries in whycode/code/languages.py. Each sample has the shapes that language
writes classes, functions and constants in."""

import pytest

from whycode.code.entities import EntityKind, is_supported, parse_file
from whycode.code.languages import language_for

REPO = "o/r"

KOTLIN = """\
package app
const val MAX_RETRIES = 3
class Router(val name: String) : Base() {
    companion object {
        const val LIMIT = 5
    }
    fun handle(req: Request, retries: Int = MAX_RETRIES): Int = 0
}
interface Handler {
    fun serve()
}
object Registry {
    fun get() {}
}
data class Point(val x: Int)
enum class Mode { A, B }
fun helper() {}
fun Router.ext() {}
"""

SWIFT = """\
let maxRetries = 3
var counter = 0
class Router: Base {
    static let `default` = Router()
    let name = "x"
    init(name: String) {}
    func handle(req: Request) -> Int { return 0 }
}
struct Point { func len() -> Int { 0 } }
protocol Handler { func serve() }
enum Mode { case a; func m() {} }
extension Router { func extra() {} }
func helper() {}
"""

SCALA = """\
package app
object Config {
  final val MaxRetries = 3
  val DEFAULT_NAME = "x"
  val cache = 1
  def load(): Unit = ()
}
class Router(name: String) extends Base {
  def handle(req: Request, retries: Int = Config.MaxRetries): Int = 0
}
trait Handler { def serve(): Unit }
case class Point(x: Int)
enum Mode { case A, B }
def helper(): Unit = ()
"""

DART = """\
const maxRetries = 3;
final started = DateTime.now();
class Router extends Base {
  static const limit = 5;
  Router(this.name);
  void handle(Request req) {
    print(req);
  }
  int get size => 0;
}
mixin Loggable { void log() {} }
enum Mode { a, b }
extension Ext on Router { void extra() {} }
void helper() {
  return;
}
"""

BASH = """\
readonly MAX_RETRIES=3
DEFAULT_NAME="x"
local_var=1
function deploy() { echo hi; }
cleanup() { rm -f x; }
"""

LUA = """\
local MAX_RETRIES = 3
local M = {}
function M.handle(req) end
function M:serve() end
local function helper() end
function global_fn() end
M.extra = function() end
return M
"""

ELIXIR = """\
defmodule App.Router do
  @timeout 5000
  @moduledoc "Routes requests."
  @spec handle(term, integer) :: :ok
  def handle(req, retries \\\\ @timeout), do: :ok
  defp helper(x) when is_integer(x) do
    x
  end
  defmacro m(x), do: x
  defmodule Inner do
    def run, do: :ok
  end
end
defprotocol App.Handler do
  def serve(x)
end
"""

HASKELL = """\
module App.Router where
maxRetries :: Int
maxRetries = 3
data Router = Router { name :: String }
newtype Id = Id Int
class Handler a where
  serve :: a -> IO ()
instance Handler Router where
  serve _ = pure ()
handle :: Router -> Int -> Int
handle r n = n
type Name = String
"""

OBJC = """\
#define MAX_RETRIES 3
static const NSInteger kLimit = 5;
@interface Router : NSObject
- (void)handle:(Request *)req;
+ (instancetype)shared;
@end
@implementation Router
- (void)handle:(Request *)req retries:(int)n { }
+ (instancetype)shared { return nil; }
@end
@protocol Handler
- (void)serve;
@end
void helper(void) {}
"""

JULIA = """\
module App
const MAX_RETRIES = 3
struct Router
    name::String
end
abstract type Handler end
function handle(r::Router, retries=MAX_RETRIES)
    0
end
size(r::Router) = 0
macro m(x) x end
end
"""

ZIG = """\
const std = @import("std");
pub const MAX_RETRIES: u32 = 3;
var counter: u32 = 0;
pub const Router = struct {
    name: []const u8,
    const LIMIT = 5;
    pub fn init(name: []const u8) Router { return .{ .name = name }; }
    fn handle(self: *Router) void {}
};
const Mode = enum { a, b };
pub fn helper() void {}
"""

OCAML = """\
let max_retries = 3
let handle req retries = 0
let helper = fun x -> x
module Router = struct
  let serve () = ()
  type t = { name : string }
end
module type HANDLER = sig val serve : unit -> unit end
type mode = A | B
class point = object method x = 0 end
"""

# path, source, {qualified name: parent's qualified name ("" for the file)} for classes and
# functions, and {qualified name: value} for config keys.
CASES = {
    "kotlin": (
        "src/main/kotlin/app/Router.kt",
        KOTLIN,
        {
            "Router": "",
            "Router.handle": "Router",
            "Handler": "",
            "Handler.serve": "Handler",
            "Registry": "",
            "Registry.get": "Registry",
            "Point": "",
            "Mode": "",
            "helper": "",
            "Router.ext": "Router",  # an extension function, named after the type it extends
        },
        {"MAX_RETRIES": "3", "Router.LIMIT": "5"},  # a companion object's members are the class's
    ),
    "swift": (
        "Sources/App/Router.swift",
        SWIFT,
        {
            "Router": "",
            "Router.init": "Router",
            "Router.handle": "Router",
            "Point": "",
            "Point.len": "Point",
            "Handler": "",
            "Handler.serve": "Handler",
            "Mode": "",
            "Mode.m": "Mode",
            "Router.extra": "Router",  # an extension names its functions after the type
            "helper": "",
        },
        {"maxRetries": "3", "Router.default": "Router()"},  # not `var`, not an instance `let`
    ),
    "scala": (
        "src/main/scala/app/Router.scala",
        SCALA,
        {
            "Config": "",
            "Config.load": "Config",
            "Router": "",
            "Router.handle": "Router",
            "Handler": "",
            "Handler.serve": "Handler",
            "Point": "",
            "Mode": "",
            "helper": "",
        },
        {
            "Config.MaxRetries": "3",
            "Config.DEFAULT_NAME": '"x"',
            "Router.handle.retries": "Config.MaxRetries",
        },
    ),
    "dart": (
        "lib/router.dart",
        DART,
        {
            "Router": "",
            "Router.Router": "Router",
            "Router.handle": "Router",
            "Router.size": "Router",
            "Loggable": "",
            "Loggable.log": "Loggable",
            "Mode": "",
            "Router.extra": "Router",
            "helper": "",
        },
        {"maxRetries": "3", "Router.limit": "5"},  # `final` is not a compile-time constant
    ),
    "bash": (
        "scripts/deploy.sh",
        BASH,
        {"deploy": "", "cleanup": ""},
        {"MAX_RETRIES": "3", "DEFAULT_NAME": '"x"'},
    ),
    "lua": (
        "lua/router.lua",
        LUA,
        {"M.handle": "", "M.serve": "", "helper": "", "global_fn": "", "M.extra": ""},
        {"MAX_RETRIES": "3"},
    ),
    "elixir": (
        "lib/app/router.ex",
        ELIXIR,
        {
            "App.Router": "",
            "App.Router.handle": "App.Router",
            "App.Router.helper": "App.Router",
            "App.Router.m": "App.Router",
            "App.Router.Inner": "App.Router",
            "App.Router.Inner.run": "App.Router.Inner",
            "App.Handler": "",
            "App.Handler.serve": "App.Handler",
        },
        {"App.Router.timeout": "5000"},  # not @moduledoc or @spec
    ),
    "haskell": (
        "src/App/Router.hs",
        HASKELL,
        {
            "Router": "",
            "Id": "",
            "Handler": "",
            "Handler.serve": "Handler",  # the instance's equation replaces the class signature
            "handle": "",
            "Name": "",
        },
        {"maxRetries": "3"},
    ),
    "objc": (
        "AFNetworking/Router.m",
        OBJC,
        {
            "Router": "",
            "Router.handle": "Router",  # the first part of the selector handle:retries:
            "Router.shared": "Router",
            "Handler": "",
            "Handler.serve": "Handler",
            "helper": "",
        },
        {"MAX_RETRIES": "3", "kLimit": "5"},
    ),
    "julia": (
        "src/App.jl",
        JULIA,
        {
            "App": "",
            "App.Router": "App",
            "App.Handler": "App",
            "App.handle": "App",
            "App.size": "App",  # the short form `size(r) = 0`
            "App.m": "App",
        },
        {"App.MAX_RETRIES": "3", "App.handle.retries": "MAX_RETRIES"},
    ),
    "zig": (
        "src/router.zig",
        ZIG,
        {
            "Router": "",  # const Router = struct {...}
            "Router.init": "Router",
            "Router.handle": "Router",
            "Mode": "",
            "helper": "",
        },
        {"MAX_RETRIES": "3", "Router.LIMIT": "5"},  # not @import, not var
    ),
    "ocaml": (
        "lib/router.ml",
        OCAML,
        {
            "handle": "",  # a let with parameters
            "helper": "",  # a let bound to fun
            "Router": "",
            "Router.serve": "Router",
            "Router.t": "Router",
            "HANDLER": "",
            "HANDLER.serve": "HANDLER",
            "mode": "",
            "point": "",
            "point.x": "point",
        },
        {"max_retries": "3"},
    ),
}


def _parents(parsed) -> dict[str, str]:
    names = {e.id: e.qualified_name for e in parsed.entities[1:]} | {parsed.entities[0].id: ""}
    return {
        e.qualified_name: names[e.parent_id]
        for e in parsed.entities[1:]
        if e.kind in (EntityKind.CLASS, EntityKind.FUNCTION)
    }


@pytest.mark.parametrize("language", sorted(CASES))
def test_classes_and_functions_nest_under_their_parents(language):
    path, source, code, _ = CASES[language]
    parsed = parse_file(REPO, path, source)
    assert not parsed.has_syntax_errors
    assert _parents(parsed) == code


@pytest.mark.parametrize("language", sorted(CASES))
def test_constants_and_defaults_that_reference_them_are_config(language):
    path, source, _, config = CASES[language]
    parsed = parse_file(REPO, path, source)
    assert {e.qualified_name: e.value for e in parsed.of_kind(EntityKind.CONFIG_KEY)} == config


@pytest.mark.parametrize("language", sorted(CASES))
def test_ids_are_unique_and_parsing_is_deterministic(language):
    path, source, _, _ = CASES[language]
    parsed = parse_file(REPO, path, source)
    ids = [e.id for e in parsed.entities]
    assert len(ids) == len(set(ids))
    assert parse_file(REPO, path, source) == parsed


def test_a_dart_method_spans_its_body():
    parsed = parse_file(REPO, "lib/router.dart", DART)
    lines = {e.qualified_name: (e.start_line, e.end_line) for e in parsed.entities}
    assert lines["Router.handle"] == (6, 8)
    assert lines["helper"] == (14, 16)


def test_a_header_that_is_objective_c_is_read_as_objective_c():
    src = "@interface Router : NSObject\n- (void)handle;\n@end\n"
    parsed = parse_file(REPO, "include/Router.h", src)
    assert not parsed.has_syntax_errors
    assert [e.qualified_name for e in parsed.entities[1:]] == ["Router", "Router.handle"]


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("a.kt", "kotlin"),
        ("build.gradle.kts", "kotlin"),
        ("a.swift", "swift"),
        ("a.scala", "scala"),
        ("a.dart", "dart"),
        ("a.sh", "bash"),
        ("a.lua", "lua"),
        ("a.ex", "elixir"),
        ("a.exs", "elixir"),
        ("a.hs", "haskell"),
        ("a.m", "objc"),
        ("a.jl", "julia"),
        ("a.zig", "zig"),
        ("a.ml", "ocaml"),
        ("a.mli", "ocaml-interface"),
    ],
)
def test_each_suffix_reads_with_its_language(path, language):
    assert language_for(path).name == language
    assert is_supported(path)


def test_generated_dart_is_left_out():
    assert not is_supported("lib/model.g.dart")
