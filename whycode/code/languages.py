"""Languages the code map reads besides Python: a tree-sitter grammar plus one query each.

Python keeps its own walker in entities.py, which has rules a query does not express simply
(decorators, if/try blocks at module level). Every other language is a QueryLanguage: entities.py
runs its query and turns the matches into entities, so adding a language means adding a grammar
and a query here, nothing else.

Each match of a query captures `@name` and exactly one of:
- @class, @function  a definition; the captured node gives its lines, @name its name. Nesting by
                     line range gives qualified names ("Router.handle", "outer.inner").
- @signature         a function declared without its body (a C prototype, a method declared in a
                     C++ class, a TypeScript overload). It is a function, but when the file also
                     has the definition, the definition is kept: changes land in the body.
- @scope             a container that only names what is inside it, with no entity of its own:
                     a Rust `impl Router` block makes its functions "Router.new", and their parent
                     the Router struct when the file has it.
- @config            a constant's declaration, with its value as @value. Inside a class it is
                     "Class.NAME". Kept only when the value is not code (see `code_values`), and,
                     for languages where any variable could match, only for UPPER_CASE names.
- @default           a parameter with a default (@value). Kept only when the default references a
                     constant, and only for the definition the parameter list belongs to.
A @function may also capture @owner, the type a method belongs to when it is declared outside it
(Go's `func (r *Router) Handle()` is "Router.Handle"). A name written with `::` names its owner
too: C++'s `void app::Router::serve()` is "Router.serve".
"""

import importlib
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import PurePosixPath

from tree_sitter import Language, Query

# Two characters or more, so single-letter type variables ("T") are not config.
UPPER_CASE = re.compile(r"^_*[A-Z][A-Z0-9_]+$")
# C++ also names constants the Google way: kMaxRetries.
CPP_CONSTANT = re.compile(r"^(_*[A-Z][A-Z0-9_]+|k[A-Z][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class QueryLanguage:
    """A language's grammar and query are built the first time a file in it is read: building
    all of them took about 4 s, which every API cold start and every code map would pay, even for
    a repo with no file in most of these languages."""

    name: str
    suffixes: frozenset[str]
    grammar: str  # "module:function" returning the tree-sitter language, imported on first use
    query_source: str
    # Value node types that make a declaration a function or class rather than config:
    # `const make = () => 1` is a function, `const LIMIT = 5` is config.
    code_values: frozenset[str] = frozenset()
    # Which declared names are config. A pattern where the query matches any variable
    # (JavaScript `const`, Java `static final`); None where the keyword itself declares a
    # constant (Go, C#, Rust and PHP `const`, Ruby constants).
    config_names: re.Pattern | None = UPPER_CASE
    # How a parameter default references a constant: node types that name one (matched against
    # ref_names, None: any name), node types that always are one (Ruby `Constant`), and member
    # accesses with the field naming the member (None: its last named child).
    ref_types: frozenset[str] = frozenset({"identifier"})
    ref_names: re.Pattern | None = UPPER_CASE
    constant_types: frozenset[str] = frozenset()
    member_name_field: dict[str, str | None] = field(default_factory=dict)
    # Node types between a parameter list and its function definition (C's declarators:
    # `char *f(int x = A)` puts a pointer declarator in between).
    declarator_types: frozenset[str] = frozenset()
    # Generated files to leave out (minified bundles, protobuf output): thousands of names.
    skipped_suffixes: tuple[str, ...] = ()
    # Another language to read the file with when this one finds syntax errors and it does not
    # (a `.h` header is C++ or C).
    fallback: "QueryLanguage | None" = None

    @cached_property
    def language(self) -> Language:
        module, function = self.grammar.split(":")
        return Language(getattr(importlib.import_module(module), function)())

    @cached_property
    def query(self) -> Query:
        return Query(self.language, self.query_source)


def _make(name: str, grammar: str, suffixes: set[str], query: str, **kw) -> QueryLanguage:
    return QueryLanguage(name, frozenset(suffixes), grammar, query, **kw)


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
(function_signature name: (identifier) @name) @signature
(method_definition name: (_) @name) @function
(method_signature name: (_) @name) @signature
(abstract_method_signature name: (_) @name) @signature
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

# C and C++ ------------------------------------------------------------------------------------

# A function's name sits inside its declarator, behind any pointer or reference in the return type.
_C_FN = (
    "[(function_declarator declarator: {n})"
    " (pointer_declarator declarator: (function_declarator declarator: {n}))"
    " (pointer_declarator declarator:"
    " (pointer_declarator declarator: (function_declarator declarator: {n})))]"
)
_CPP_FN = (
    "[(function_declarator declarator: {n})"
    " (pointer_declarator declarator: (function_declarator declarator: {n}))"
    " (pointer_declarator declarator:"
    " (pointer_declarator declarator: (function_declarator declarator: {n})))"
    " (reference_declarator (function_declarator declarator: {n}))]"
)
_C_NAME = "(identifier) @name"
_CPP_NAME = (
    "[(identifier) (field_identifier) (destructor_name) (operator_name) (qualified_identifier)]"
    " @name"
)
# Where file-level declarations sit: the file itself, or an include guard or #if block around them.
_C_TOP = ("translation_unit", "preproc_ifdef", "preproc_if", "preproc_else", "preproc_elif")
_C_CONST = "(init_declarator declarator: (identifier) @name value: (_) @value)"
_IS_CONST = '(#eq? @q "const")'


def _at_top(pattern: str, parents) -> str:
    return "\n".join(f"({p} {pattern})" for p in parents)


_RECORDS = """
(struct_specifier name: {n} body: (_)) @class
(union_specifier name: {n} body: (_)) @class
(enum_specifier name: {n} body: (_)) @class
(type_definition
  type: [(struct_specifier !name body: (_)) (union_specifier !name body: (_))
         (enum_specifier !name body: (_))]
  declarator: (type_identifier) @name) @class
"""
_C_RECORDS = _RECORDS.format(n="(type_identifier) @name")
# C++ may define a nested type outside its class: `struct DBImpl::Writer {...}` is DBImpl.Writer.
_CPP_TYPE_NAME = "[(type_identifier) (qualified_identifier)] @name"
_CPP_RECORDS = _RECORDS.format(n=_CPP_TYPE_NAME)

# Structs, unions and enums with a body (also unnamed ones a typedef names); functions;
# prototypes at file level; #define constants and file-level const variables.
C_QUERY = f"""
{_C_RECORDS}
(function_definition declarator: {_C_FN.format(n=_C_NAME)}) @function
{_at_top(f"(declaration declarator: {_C_FN.format(n=_C_NAME)}) @signature", _C_TOP)}

(preproc_def name: (identifier) @name value: (_) @value) @config
{_at_top(f"((declaration (type_qualifier) @q declarator: {_C_CONST}) @config {_IS_CONST})", _C_TOP)}
"""

# C's patterns plus classes and templates. Methods defined outside their class are named after it
# (`void Router::serve()` is "Router.serve", and replaces the declaration inside the class).
# Namespaces are left out of names, as Java packages and C# namespaces are.
_CPP_TOP = (*_C_TOP, "declaration_list")
CPP_QUERY = f"""
{_CPP_RECORDS}
(class_specifier name: {_CPP_TYPE_NAME} body: (_)) @class

(function_definition declarator: {_CPP_FN.format(n=_CPP_NAME)}) @function
{_at_top(f"(declaration declarator: {_CPP_FN.format(n=_CPP_NAME)}) @signature", _CPP_TOP)}
(field_declaration_list (declaration declarator: {_CPP_FN.format(n=_CPP_NAME)}) @signature)
(field_declaration_list (field_declaration declarator: {_CPP_FN.format(n=_CPP_NAME)}) @signature)

(preproc_def name: (identifier) @name value: (_) @value) @config
{
    _at_top(
        f"((declaration (type_qualifier) @q declarator: {_C_CONST}) @config"
        ' (#any-of? @q "const" "constexpr"))',
        _CPP_TOP,
    )
}
((field_declaration (storage_class_specifier) @s (type_qualifier) @q
   declarator: (field_identifier) @name default_value: (_) @value) @config
 (#eq? @s "static") (#any-of? @q "const" "constexpr"))

(optional_parameter_declaration declarator: (identifier) @name default_value: (_) @value) @default
"""

_C_DECLARATORS = frozenset({"function_declarator", "pointer_declarator", "reference_declarator"})

# Kotlin ---------------------------------------------------------------------------------------

# Classes cover interfaces, data, enum and sealed classes; objects count too. A companion
# object's members belong to the class around it. Extension functions are named after the type
# they extend ("Router.ext"). Constants are `const val`.
KOTLIN_QUERY = """
(class_declaration name: (identifier) @name) @class
(object_declaration name: (identifier) @name) @class

(function_declaration name: (identifier) @name) @function
(function_declaration (user_type (identifier) @owner) . name: (identifier) @name) @function

((property_declaration (modifiers (property_modifier) @mod)
   (variable_declaration (identifier) @name) . (_) @value) @config
 (#eq? @mod "const"))
"""

# Swift ----------------------------------------------------------------------------------------

# class, struct, enum and actor declarations are class_declaration; an extension only names what
# is inside it. Constants are `let` at file level and `static let` in a type.
SWIFT_QUERY = """
(class_declaration name: (type_identifier) @name) @class
(class_declaration name: (user_type (type_identifier) @name)) @scope
(protocol_declaration name: (type_identifier) @name) @class

(function_declaration name: (simple_identifier) @name) @function
(protocol_function_declaration name: (simple_identifier) @name) @signature
(init_declaration "init" @name) @function
(deinit_declaration "deinit" @name) @function

((source_file (property_declaration (value_binding_pattern) @kind
   name: (pattern bound_identifier: (simple_identifier) @name) value: (_) @value) @config)
 (#eq? @kind "let"))
((property_declaration (modifiers (property_modifier) @mod) (value_binding_pattern) @kind
   name: (pattern bound_identifier: (simple_identifier) @name) value: (_) @value) @config
 (#eq? @mod "static") (#eq? @kind "let"))
"""

# Scala ----------------------------------------------------------------------------------------

# Constants are vals in an object or at file level, named the Scala way (MaxRetries, MAX).
SCALA_QUERY = """
(class_definition name: (identifier) @name) @class
(object_definition name: (identifier) @name) @class
(trait_definition name: (identifier) @name) @class
(enum_definition name: (identifier) @name) @class

(function_definition name: (identifier) @name) @function
(function_declaration name: (identifier) @name) @signature

(object_definition body: (template_body
  (val_definition pattern: (identifier) @name value: (_) @value) @config))
(compilation_unit (val_definition pattern: (identifier) @name value: (_) @value) @config)

(parameters (parameter name: (identifier) @name default_value: (_) @value) @default)
"""

# Dart -----------------------------------------------------------------------------------------

_DART_SIGNATURE = (
    "[(function_signature name: (identifier) @name) (getter_signature name: (identifier) @name)"
    " (setter_signature name: (identifier) @name)"
    " (constructor_signature name: (identifier) @name)]"
)
# A method's body follows its signature as a sibling, so @end stretches the method over it. An
# extension names its methods after the type it extends. Constants are `const`.
DART_QUERY = f"""
(class_definition name: (identifier) @name) @class
(mixin_declaration (mixin) . (identifier) @name) @class
(enum_declaration name: (identifier) @name) @class
(extension_declaration class: (type_identifier) @name) @scope

((method_signature {_DART_SIGNATURE}) @function . (function_body) @end)
((function_signature name: (identifier) @name) @function . (function_body) @end)
(declaration (constructor_signature name: (identifier) @name)) @function
(declaration (function_signature name: (identifier) @name)) @signature

(program (const_builtin) . (static_final_declaration_list
  (static_final_declaration (identifier) @name . (_) @value) @config))
(declaration (const_builtin) . (static_final_declaration_list
  (static_final_declaration (identifier) @name . (_) @value) @config))
"""

# Bash -----------------------------------------------------------------------------------------

# Functions; UPPER_CASE variables set at file level (also through readonly, export, declare).
BASH_QUERY = """
(function_definition name: (word) @name) @function

(program (variable_assignment name: (variable_name) @name value: (_) @value) @config)
(program (declaration_command (variable_assignment name: (variable_name) @name value: (_) @value))
  @config)
"""

# Lua ------------------------------------------------------------------------------------------

# `function M.handle()` and `M.extra = function() end` are named after their table ("M.handle").
LUA_QUERY = """
(function_declaration name: (identifier) @name) @function
(function_declaration
  name: (dot_index_expression table: (identifier) @owner field: (identifier) @name)) @function
(function_declaration
  name: (method_index_expression table: (identifier) @owner method: (identifier) @name)) @function
(assignment_statement
  (variable_list name: (dot_index_expression table: (identifier) @owner field: (identifier) @name))
  (expression_list value: (function_definition))) @function
(variable_declaration (assignment_statement (variable_list name: (identifier) @name)
  (expression_list value: (function_definition)))) @function

(chunk (variable_declaration (assignment_statement (variable_list name: (identifier) @name)
  (expression_list value: (_) @value))) @config)
"""

# Elixir ---------------------------------------------------------------------------------------

# Everything is a call: `defmodule App.Router do`, `def handle(x)`, `defp`, macros and guards.
# Module attributes (`@timeout 5000`) are config, except the documentation and typing ones.
ELIXIR_QUERY = """
((call target: (identifier) @kw (arguments (alias) @name)) @class
 (#any-of? @kw "defmodule" "defprotocol"))

((call target: (identifier) @kw
   (arguments [(call target: (identifier) @name) (identifier) @name
               (binary_operator left: (call target: (identifier) @name))])) @function
 (#any-of? @kw "def" "defp" "defmacro" "defmacrop" "defguard" "defguardp" "defdelegate"))

((unary_operator operator: "@" operand: (call target: (identifier) @name (arguments . (_) @value)))
  @config)
"""

# Haskell --------------------------------------------------------------------------------------

# Data types, newtypes, type classes and synonyms are classes; an instance names its functions
# after the class. Functions are equations with parameters; a top-level binding to a literal
# (`maxRetries = 3`) is config.
HASKELL_QUERY = """
(data_type name: (name) @name) @class
(newtype name: (name) @name) @class
(class name: (name) @name) @class
(type_synonym name: (name) @name) @class
(instance name: (name) @name) @scope

(function name: (variable) @name) @function
(class_declarations (signature name: (variable) @name) @signature)

(declarations (bind name: (variable) @name match: (match expression: (literal) @value)) @config)
"""

# Objective-C ----------------------------------------------------------------------------------

# C's patterns plus @interface, @implementation and @protocol; a method is named by the first part
# of its selector (`- (void)handle:(id)x retries:(int)n` is "handle").
OBJC_QUERY = f"""
{_C_RECORDS}
(class_interface . (identifier) @name) @class
(class_implementation . (identifier) @name) @class
(protocol_declaration . (identifier) @name) @class

(method_definition (method_type) . (identifier) @name) @function
(method_definition . (identifier) @name) @function
(method_declaration (method_type) . (identifier) @name) @signature
(method_declaration . (identifier) @name) @signature
(function_definition declarator: {_C_FN.format(n=_C_NAME)}) @function
{_at_top(f"(declaration declarator: {_C_FN.format(n=_C_NAME)}) @signature", _C_TOP)}

(preproc_def name: (identifier) @name value: (_) @value) @config
{_at_top(f"((declaration (type_qualifier) @q declarator: {_C_CONST}) @config {_IS_CONST})", _C_TOP)}
"""

# Julia ----------------------------------------------------------------------------------------

JULIA_QUERY = """
(module_definition name: (identifier) @name) @class
(struct_definition (type_head (identifier) @name)) @class
(abstract_definition (type_head (identifier) @name)) @class

(function_definition (signature (call_expression . (identifier) @name))) @function
(assignment . (call_expression . (identifier) @name)) @function
(macro_definition (signature (call_expression . (identifier) @name))) @function

(const_statement (assignment . (identifier) @name (operator) . (_) @value)) @config

(argument_list (named_argument . (identifier) @name (operator) . (_) @value) @default)
"""

# Zig ------------------------------------------------------------------------------------------

# A type is a constant bound to a struct, enum, union or opaque ("const Router = struct {...}").
# Other UPPER_CASE constants are config.
ZIG_QUERY = """
(variable_declaration (identifier) @name
  [(struct_declaration) (enum_declaration) (union_declaration) (opaque_declaration)]) @class

(function_declaration name: (identifier) @name) @function

(variable_declaration "const" (identifier) @name (_) @value .) @config
"""

# OCaml ----------------------------------------------------------------------------------------

# Modules, module types, classes and types are classes. A let with parameters (or bound to `fun`)
# is a function; a top-level let bound to a literal is config.
OCAML_QUERY = """
(module_definition (module_binding (module_name) @name)) @class
(module_type_definition (module_type_name) @name) @class
(class_definition (class_binding (class_name) @name)) @class
(type_definition (type_binding name: (type_constructor) @name)) @class

(let_binding pattern: (value_name) @name (parameter)) @function
(let_binding pattern: (value_name) @name body: [(fun_expression) (function_expression)]) @function
(method_definition (method_name) @name) @function
(value_specification (value_name) @name) @signature

(value_definition (let_binding pattern: (value_name) @name
  body: [(number) (string) (boolean) (signed_number)] @value)) @config
"""

# ----------------------------------------------------------------------------------------------

JAVASCRIPT = _make(
    "javascript",
    "tree_sitter_javascript:language",
    {".js", ".mjs", ".cjs", ".jsx"},
    JAVASCRIPT_QUERY,
    skipped_suffixes=(".min.js", ".min.mjs", ".min.cjs"),
    **_JS_LIKE,
)
TYPESCRIPT = _make(
    "typescript",
    "tree_sitter_typescript:language_typescript",
    {".ts", ".mts", ".cts"},
    TYPESCRIPT_QUERY,
    **_JS_LIKE,
)
TSX = _make("tsx", "tree_sitter_typescript:language_tsx", {".tsx"}, TYPESCRIPT_QUERY, **_JS_LIKE)
JAVA = _make("java", "tree_sitter_java:language", {".java"}, JAVA_QUERY)
GO = _make(
    "go",
    "tree_sitter_go:language",
    {".go"},
    GO_QUERY,
    config_names=None,
    skipped_suffixes=(".pb.go",),
)
CSHARP = _make(
    "csharp",
    "tree_sitter_c_sharp:language",
    {".cs"},
    CSHARP_QUERY,
    config_names=None,
    ref_names=None,
    member_name_field={"member_access_expression": "name"},
    skipped_suffixes=(".g.cs", ".designer.cs"),
)
RUST = _make("rust", "tree_sitter_rust:language", {".rs"}, RUST_QUERY, config_names=None)
RUBY = _make(
    "ruby",
    "tree_sitter_ruby:language",
    {".rb"},
    RUBY_QUERY,
    code_values=frozenset({"lambda"}),
    config_names=None,
    ref_types=frozenset(),
    constant_types=frozenset({"constant"}),
    member_name_field={"scope_resolution": "name"},
)
PHP = _make(
    "php",
    "tree_sitter_php:language_php",
    {".php"},
    PHP_QUERY,
    config_names=None,
    ref_types=frozenset({"name"}),
    ref_names=None,
    member_name_field={"class_constant_access_expression": None},
)
OBJC = _make(
    "objc",
    "tree_sitter_objc:language",
    {".m", ".mm"},
    OBJC_QUERY,
    config_names=CPP_CONSTANT,  # Apple names constants kName too
    declarator_types=_C_DECLARATORS,
)
# A C file the C grammar trips on may be Objective-C, which extends C.
C = _make(
    "c", "tree_sitter_c:language", {".c"}, C_QUERY, declarator_types=_C_DECLARATORS, fallback=OBJC
)
_CPP = {
    "code_values": frozenset({"lambda_expression"}),
    "config_names": CPP_CONSTANT,
    "ref_names": CPP_CONSTANT,
    "member_name_field": {"qualified_identifier": "name", "field_expression": "field"},
    "declarator_types": _C_DECLARATORS,
}
CPP = _make(
    "cpp",
    "tree_sitter_cpp:language",
    {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"},
    CPP_QUERY,
    **_CPP,
)
# A .h header is read as C++ (which also reads most C), then as C and as Objective-C when the
# one before finds syntax errors.
HEADER = _make("c-or-cpp-header", "tree_sitter_cpp:language", {".h"}, CPP_QUERY, fallback=C, **_CPP)
KOTLIN = _make(
    "kotlin", "tree_sitter_kotlin:language", {".kt", ".kts"}, KOTLIN_QUERY, config_names=None
)
SWIFT = _make("swift", "tree_sitter_swift:language", {".swift"}, SWIFT_QUERY, config_names=None)
_SCALA_CONSTANT = re.compile(r"^[A-Z][A-Za-z0-9_]*$")  # MaxRetries or MAX_RETRIES
SCALA = _make(
    "scala",
    "tree_sitter_scala:language",
    {".scala", ".sc"},
    SCALA_QUERY,
    config_names=_SCALA_CONSTANT,
    ref_names=_SCALA_CONSTANT,
    member_name_field={"field_expression": "field"},
)
DART = _make(
    "dart",
    "tree_sitter_dart:language",
    {".dart"},
    DART_QUERY,
    config_names=None,
    skipped_suffixes=(".g.dart",),
)
BASH = _make("bash", "tree_sitter_bash:language", {".sh", ".bash"}, BASH_QUERY)
LUA = _make(
    "lua",
    "tree_sitter_lua:language",
    {".lua"},
    LUA_QUERY,
    code_values=frozenset({"function_definition"}),
)
# Attributes that document or type a module rather than configure it.
_ELIXIR_CONFIG = re.compile(
    r"^(?!(moduledoc|doc|typedoc|spec|type|typep|opaque|callback|macrocallback|impl|behaviour"
    r"|derive|enforce_keys|external_resource|compile|dialyzer|on_load|vsn|optional_callbacks"
    r"|before_compile|after_compile|on_definition|deprecated)$)[a-z_][A-Za-z0-9_]*$"
)
ELIXIR = _make(
    "elixir",
    "tree_sitter_elixir:language",
    {".ex", ".exs"},
    ELIXIR_QUERY,
    config_names=_ELIXIR_CONFIG,
)
HASKELL = _make(
    "haskell", "tree_sitter_haskell:language", {".hs"}, HASKELL_QUERY, config_names=None
)
JULIA = _make(
    "julia",
    "tree_sitter_julia:language",
    {".jl"},
    JULIA_QUERY,
    config_names=None,
    declarator_types=frozenset({"call_expression", "signature"}),
)
ZIG = _make(
    "zig",
    "tree_sitter_zig:language",
    {".zig"},
    ZIG_QUERY,
    code_values=frozenset(
        {
            "builtin_function",
            "struct_declaration",
            "enum_declaration",
            "union_declaration",
            "opaque_declaration",
            "error_set_declaration",
        }
    ),
)
OCAML = _make("ocaml", "tree_sitter_ocaml:language_ocaml", {".ml"}, OCAML_QUERY, config_names=None)
OCAML_INTERFACE = _make(
    "ocaml-interface",
    "tree_sitter_ocaml:language_ocaml_interface",
    {".mli"},
    OCAML_QUERY,
    config_names=None,
)

QUERY_LANGUAGES = (
    JAVASCRIPT,
    TYPESCRIPT,
    TSX,
    JAVA,
    GO,
    CSHARP,
    RUST,
    RUBY,
    PHP,
    C,
    CPP,
    HEADER,
    OBJC,
    KOTLIN,
    SWIFT,
    SCALA,
    DART,
    BASH,
    LUA,
    ELIXIR,
    HASKELL,
    JULIA,
    ZIG,
    OCAML,
    OCAML_INTERFACE,
)


def language_for(path: str) -> QueryLanguage | None:
    """The query language that reads this file, or None (Python files included: not a query
    language)."""
    p = PurePosixPath(path.replace("\\", "/"))
    for lang in QUERY_LANGUAGES:
        if p.suffix in lang.suffixes and not p.name.lower().endswith(lang.skipped_suffixes):
            return lang
    return None
