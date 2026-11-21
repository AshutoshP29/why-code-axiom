"""Languages the code map reads besides Python: a tree-sitter grammar plus one query each.

Python keeps its own walker in entities.py, which has rules a query does not express simply
(decorators, if/try blocks at module level). Every other language is a QueryLanguage: entities.py
runs its query and turns the matches into entities, so adding a language means adding a grammar
and a query here, nothing else.

Each match of a query captures `@name` and exactly one of:
- @class, @function  a definition; the captured node gives its lines, @name its name. Nesting by
                     line range gives qualified names ("Router.handle", "outer.inner").
- @scope             a container that only names what is inside it, with no entity of its own:
                     a Rust `impl Router` block makes its functions "Router.new", and their parent
                     the Router struct when the file has it.
- @config            a constant's declaration, with its value as @value. Inside a class it is
                     "Class.NAME". Kept only when the value is not code (see `code_values`), and,
                     for languages where any variable could match, only for UPPER_CASE names.
- @default           a parameter with a default (@value). Kept only when the default references a
                     constant, and only for the definition the parameter list belongs to.
A @function may also capture @owner, the type a method belongs to when it is declared outside it
(Go's `func (r *Router) Handle()` is "Router.Handle").
"""

from dataclasses import dataclass, field
from pathlib import PurePosixPath

import tree_sitter_c_sharp as tscsharp
import tree_sitter_go as tsgo
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjs
import tree_sitter_php as tsphp
import tree_sitter_ruby as tsruby
import tree_sitter_rust as tsrust
import tree_sitter_typescript as tsts
from tree_sitter import Language, Query


@dataclass(frozen=True)
class QueryLanguage:
    name: str
    suffixes: frozenset[str]
    language: Language
    query: Query
    # Value node types that make a declaration a function or class rather than config:
    # `const make = () => 1` is a function, `const LIMIT = 5` is config.
    code_values: frozenset[str] = frozenset()
    # True where the query matches any variable (JavaScript `const`, Java `static final`), so
    # only UPPER_CASE names are config; False where the keyword itself declares a constant
    # (Go, C#, Rust and PHP `const`, Ruby constants).
    config_upper_only: bool = True
    # How a parameter default references a constant: node types that name one (checked for
    # UPPER_CASE when ref_upper_only), node types that always are one (Ruby `Constant`), and
    # member accesses with the field naming the member (None: its last named child).
    ref_types: frozenset[str] = frozenset({"identifier"})
    ref_upper_only: bool = True
    constant_types: frozenset[str] = frozenset()
    member_name_field: dict[str, str | None] = field(default_factory=dict)
    # Generated files to leave out (minified bundles, protobuf output): thousands of names.
    skipped_suffixes: tuple[str, ...] = ()


def _make(name: str, language_ptr, suffixes: set[str], query: str, **kw) -> QueryLanguage:
    language = Language(language_ptr)
    return QueryLanguage(name, frozenset(suffixes), language, Query(language, query), **kw)


# JavaScript and TypeScript ---------------------------------------------------------------------

_JS_FUNCTION = "[(arrow_function) (function_expression) (generator_function)]"
_JS_DECLARATOR = "(variable_declarator name: (identifier) @name value: (_) @value)"
_JS_DECLARATION = (
    f"[(lexical_declaration {_JS_DECLARATOR}) (variable_declaration {_JS_DECLARATOR})]"
)
_JS_CODE_VALUES = frozenset(
    {"arrow_function", "function_expression", "generator_function", "class"}
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
(field_definition property: (property_identifier) @name value: {_JS_FUNCTION}) @function

(program {_JS_DECLARATION} @config)
(program (export_statement declaration: {_JS_DECLARATION}) @config)

(formal_parameters (assignment_pattern left: (identifier) @name right: (_) @value) @default)
"""

# TypeScript's grammar extends JavaScript's: the same patterns plus interfaces, enums, abstract
# classes, signatures and typed parameters. Namespaces only name what is inside them.
TYPESCRIPT_QUERY = f"""
(class_declaration name: (_) @name) @class
(abstract_class_declaration name: (_) @name) @class
(class name: (_) @name) @class
(variable_declarator name: (identifier) @name value: (class !name)) @class
(interface_declaration name: (_) @name) @class
(enum_declaration name: (_) @name) @class
(internal_module name: (_) @name) @scope

(function_declaration name: (identifier) @name) @function
(generator_function_declaration name: (identifier) @name) @function
(function_signature name: (identifier) @name) @function
(method_definition name: (_) @name) @function
(method_signature name: (_) @name) @function
(abstract_method_signature name: (_) @name) @function
(variable_declarator name: (identifier) @name value: {_JS_FUNCTION}) @function
(assignment_expression
  left: [(identifier) @name (member_expression property: (property_identifier) @name)]
  right: {_JS_FUNCTION}) @function
(pair key: [(property_identifier) (string)] @name value: {_JS_FUNCTION}) @function
(public_field_definition name: (property_identifier) @name value: {_JS_FUNCTION}) @function

(program {_JS_DECLARATION} @config)
(program (export_statement declaration: {_JS_DECLARATION}) @config)

(formal_parameters (required_parameter pattern: (identifier) @name value: (_) @value) @default)
(formal_parameters (optional_parameter pattern: (identifier) @name value: (_) @value) @default)
"""

_JS_LIKE = {
    "code_values": _JS_CODE_VALUES,
    "member_name_field": {"member_expression": "property"},
}

# Java -----------------------------------------------------------------------------------------

# Constants are `static final` fields (interface fields are implicitly so); a constructor is named
# after its class, as Java writes it ("Router.Router").
JAVA_QUERY = """
(class_declaration name: (identifier) @name) @class
(interface_declaration name: (identifier) @name) @class
(enum_declaration name: (identifier) @name) @class
(record_declaration name: (identifier) @name) @class
(annotation_type_declaration name: (identifier) @name) @class

(method_declaration name: (identifier) @name) @function
(constructor_declaration name: (identifier) @name) @function
(compact_constructor_declaration name: (identifier) @name) @function

((field_declaration (modifiers) @mods
   declarator: (variable_declarator name: (identifier) @name value: (_) @value)) @config
 (#match? @mods "(^|\\\\s)static(\\\\s|$)")
 (#match? @mods "(^|\\\\s)final(\\\\s|$)"))
(constant_declaration
  declarator: (variable_declarator name: (identifier) @name value: (_) @value)) @config
"""

# Go -------------------------------------------------------------------------------------------

_GO_RECEIVER = (
    "[(type_identifier) @owner (pointer_type (type_identifier) @owner)"
    " (generic_type type: (type_identifier) @owner)"
    " (pointer_type (generic_type type: (type_identifier) @owner))]"
)
# Methods are declared outside their type; the receiver names it ("Router.Handle"). Interface
# methods nest in their type by line range. Constants are package-level `const`.
GO_QUERY = f"""
(type_spec name: (type_identifier) @name) @class
(type_alias name: (type_identifier) @name) @class

(function_declaration name: (identifier) @name) @function
(method_declaration
  receiver: (parameter_list (parameter_declaration type: {_GO_RECEIVER}))
  name: (field_identifier) @name) @function
(method_elem name: (field_identifier) @name) @function

(source_file (const_declaration (const_spec name: (identifier) @name value: (_) @value) @config))
"""

# C# -------------------------------------------------------------------------------------------

# Constants are `const` fields and `readonly` fields with a value. Properties count as functions.
# A parameter default must be a compile-time constant, so any name in one is a constant.
CSHARP_QUERY = """
(class_declaration name: (identifier) @name) @class
(interface_declaration name: (identifier) @name) @class
(struct_declaration name: (identifier) @name) @class
(enum_declaration name: (identifier) @name) @class
(record_declaration name: (identifier) @name) @class

(method_declaration name: (identifier) @name) @function
(constructor_declaration name: (identifier) @name) @function
(property_declaration name: (identifier) @name) @function
(local_function_statement name: (identifier) @name) @function

((field_declaration (modifier) @mod
   (variable_declaration (variable_declarator name: (identifier) @name . (_) @value))) @config
 (#any-of? @mod "const" "readonly"))

(parameter_list (parameter name: (identifier) @name . (_) @value) @default)
"""

# Rust -----------------------------------------------------------------------------------------

_RUST_TYPE = (
    "[(type_identifier) @name (generic_type type: (type_identifier) @name)"
    " (scoped_type_identifier name: (type_identifier) @name)]"
)
# `impl Router` and inline `mod` blocks only name their items; constants are `const` and `static`
# items, at any level ("Router.LIMIT" inside an impl).
RUST_QUERY = f"""
(struct_item name: (type_identifier) @name) @class
(enum_item name: (type_identifier) @name) @class
(union_item name: (type_identifier) @name) @class
(trait_item name: (type_identifier) @name) @class
(impl_item type: {_RUST_TYPE}) @scope
(mod_item name: (identifier) @name body: (_)) @scope

(function_item name: (identifier) @name) @function
(function_signature_item name: (identifier) @name) @function

(const_item name: (identifier) @name value: (_) @value) @config
(static_item name: (identifier) @name value: (_) @value) @config
"""

# Ruby -----------------------------------------------------------------------------------------

_RUBY_NAME = "[(constant) @name (scope_resolution name: (constant) @name)]"
# Modules count as classes: they hold methods (mixins). Any assignment to a Constant is config.
RUBY_QUERY = f"""
(class name: {_RUBY_NAME}) @class
(module name: {_RUBY_NAME}) @class

(method name: (_) @name) @function
(singleton_method name: (_) @name) @function

(assignment left: (constant) @name right: (_) @value) @config

(optional_parameter name: (identifier) @name value: (_) @value) @default
(keyword_parameter name: (identifier) @name value: (_) @value) @default
"""

# PHP ------------------------------------------------------------------------------------------

# Constants are `const`, at file level or in a class. A default must be a constant expression.
PHP_QUERY = """
(class_declaration name: (name) @name) @class
(interface_declaration name: (name) @name) @class
(trait_declaration name: (name) @name) @class
(enum_declaration name: (name) @name) @class

(method_declaration name: (name) @name) @function
(function_definition name: (name) @name) @function

(const_declaration (const_element (name) @name . (_) @value)) @config

(simple_parameter name: (variable_name (name) @name) default_value: (_) @value) @default
"""

# ----------------------------------------------------------------------------------------------

JAVASCRIPT = _make(
    "javascript",
    tsjs.language(),
    {".js", ".mjs", ".cjs", ".jsx"},
    JAVASCRIPT_QUERY,
    skipped_suffixes=(".min.js", ".min.mjs", ".min.cjs"),
    **_JS_LIKE,
)
TYPESCRIPT = _make(
    "typescript", tsts.language_typescript(), {".ts", ".mts", ".cts"}, TYPESCRIPT_QUERY, **_JS_LIKE
)
TSX = _make("tsx", tsts.language_tsx(), {".tsx"}, TYPESCRIPT_QUERY, **_JS_LIKE)
JAVA = _make("java", tsjava.language(), {".java"}, JAVA_QUERY)
GO = _make(
    "go",
    tsgo.language(),
    {".go"},
    GO_QUERY,
    config_upper_only=False,
    skipped_suffixes=(".pb.go",),
)
CSHARP = _make(
    "csharp",
    tscsharp.language(),
    {".cs"},
    CSHARP_QUERY,
    config_upper_only=False,
    ref_upper_only=False,
    member_name_field={"member_access_expression": "name"},
    skipped_suffixes=(".g.cs", ".designer.cs"),
)
RUST = _make("rust", tsrust.language(), {".rs"}, RUST_QUERY, config_upper_only=False)
RUBY = _make(
    "ruby",
    tsruby.language(),
    {".rb"},
    RUBY_QUERY,
    code_values=frozenset({"lambda"}),
    config_upper_only=False,
    ref_types=frozenset(),
    constant_types=frozenset({"constant"}),
    member_name_field={"scope_resolution": "name"},
)
PHP = _make(
    "php",
    tsphp.language_php(),
    {".php"},
    PHP_QUERY,
    config_upper_only=False,
    ref_types=frozenset({"name"}),
    ref_upper_only=False,
    member_name_field={"class_constant_access_expression": None},
)

QUERY_LANGUAGES = (JAVASCRIPT, TYPESCRIPT, TSX, JAVA, GO, CSHARP, RUST, RUBY, PHP)


def language_for(path: str) -> QueryLanguage | None:
    """The query language that reads this file, or None (Python files included: not a query
    language)."""
    p = PurePosixPath(path.replace("\\", "/"))
    for lang in QUERY_LANGUAGES:
        if p.suffix in lang.suffixes and not p.name.lower().endswith(lang.skipped_suffixes):
            return lang
    return None
