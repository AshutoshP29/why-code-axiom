"""Code entities in one source file, parsed with tree-sitter: File, Class, Function, ConfigKey.

Python is read by the walker below. JavaScript, TypeScript, Java, Go, C#, Rust, Ruby and PHP
are read by running each language's query from whycode/code/languages.py (_QueryWalker), with
the same rules wherever the language has the construct.

Only parsing lives here. The caller supplies the file's text (from disk or a git blob) and gets
back entities with graph ids from whycode/ids.py; writing them to Neo4j is someone else's job.

Rules:
- Lines are 1-based and inclusive. A decorated definition starts at its first decorator.
- Qualified names are dotted from the module down: "Session.rebuild_auth", "outer.inner".
- ConfigKeys are module-level UPPER_CASE assignments, including inside module-level if/try
  blocks, and function parameters whose default references a constant: an UPPER_CASE name or
  an attribute ending in one (`max_retries=DEFAULT_RETRIES`, `timeout=settings.TIMEOUT`).
  Literal defaults (`params=None`, `stream=False`, `retries=3`) are ordinary parameters.
  ConfigKey ids are "<repo>#cfg:<name>" as schema.cypher says, so the same key in two files
  is one graph node; `path` says where this one was found.
- An id seen twice in one file (property setters, if/else redefinitions) keeps the first.
- A file with syntax errors still yields whatever tree-sitter recovered, with the flag set.

The other languages, as their queries in languages.py find them:
- Classes are each language's type declarations: classes, interfaces, enums, records, structs,
  traits, Ruby modules. Namespaces and Rust `impl`/`mod` blocks only name what is inside them.
- Functions are functions, methods (constructors, getters and setters included), C# properties,
  and in JavaScript/TypeScript functions assigned to a name: `const f = () => {}`,
  `res.send = function send() {}` ("send"). Callbacks passed as arguments are not entities.
  A Go method is named after its receiver's type ("Router.Handle").
- ConfigKeys are constants, inside a class as "Class.NAME": UPPER_CASE top-level `const`/`let`/
  `var` in JavaScript/TypeScript (class fields are not, as for Python), UPPER_CASE `static
  final` fields in Java, and any `const` in Go, C#, Rust and PHP, C# `readonly` fields with a
  value, Rust `static`s, Ruby constants. Also parameter defaults that reference a constant
  (`retries = MAX_RETRIES`, `timeout = config.TIMEOUT`).
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser, QueryCursor

from whycode.code.languages import QUERY_LANGUAGES, QueryLanguage, language_for
from whycode.ids import make_id, normalize_repo

_PYTHON_SUFFIX = ".py"
# Every suffix some parser reads. is_supported() is the real test: it also leaves out minified
# bundles such as app.min.js.
SUPPORTED_SUFFIXES = frozenset({_PYTHON_SUFFIX}).union(*(lang.suffixes for lang in QUERY_LANGUAGES))

_LANGUAGE = Language(tspython.language())
# Two characters or more, so single-letter TypeVars ("T = TypeVar('T')") are not config.
_UPPER_RE = re.compile(r"^_*[A-Z][A-Z0-9_]+$")
_STATEMENT_WRAPPERS = frozenset({"assignment", "expression_statement"})
_MAX_VALUE_CHARS = 200


class EntityKind(StrEnum):
    """Values are the Neo4j labels the graph writer uses."""

    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    CONFIG_KEY = "ConfigKey"


@dataclass(frozen=True)
class CodeEntity:
    id: str
    repo: str
    kind: EntityKind
    name: str  # "rebuild_auth"
    qualified_name: str  # "Session.rebuild_auth"; a File's is its base name
    path: str  # repo-relative, forward slashes
    start_line: int
    end_line: int
    parent_id: str | None  # enclosing File, Class or Function; None for the File itself
    # A ConfigKey's assigned value or default as source text ("0", "DEFAULT_RETRIES"),
    # whitespace collapsed and clipped; None for other kinds. Phase 2 compares it across
    # commits to spot a key later set to a different value.
    value: str | None = None


@dataclass(frozen=True)
class ParsedFile:
    path: str
    entities: tuple[CodeEntity, ...]  # the File first, then in source order
    has_syntax_errors: bool

    def of_kind(self, kind: EntityKind) -> list[CodeEntity]:
        return [e for e in self.entities if e.kind is kind]


class UnsupportedFileError(ValueError):
    pass


def _is_python(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).suffix == _PYTHON_SUFFIX


def is_supported(path: str) -> bool:
    return _is_python(path) or language_for(path) is not None


def normalize_path(path: str) -> str:
    """Repo-relative POSIX path. Raises on absolute paths or ones that leave the repo."""
    p = PurePosixPath(path.replace("\\", "/"))
    if p.is_absolute() or re.match(r"^[A-Za-z]:", str(p)) or ".." in p.parts:
        raise ValueError(f"path must be relative to the repo root, got {path!r}")
    norm = str(p)
    if norm in ("", "."):
        raise ValueError("path must name a file")
    return norm


def parse_file(repo: str, path: str, source: bytes | str) -> ParsedFile:
    """Parse one code file into its entities. Raises UnsupportedFileError for other types."""
    path = normalize_path(path)
    lang = None if _is_python(path) else language_for(path)
    if lang is None and not _is_python(path):
        raise UnsupportedFileError(f"not a supported code file: {path!r}")
    data = source.encode("utf-8") if isinstance(source, str) else source
    if lang is None:
        tree = Parser(_LANGUAGE).parse(data)
        return _Walker(normalize_repo(repo), path).run(tree.root_node, data)
    tree = Parser(lang.language).parse(data)
    return _QueryWalker(normalize_repo(repo), path, lang).run(tree.root_node, data)


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None and node.text else ""


def _line_count(data: bytes) -> int:
    return max(1, data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1))


def _end_line(node: Node) -> int:
    # A node that ends at column 0 stops at the start of the next line, not on it.
    row, col = node.end_point
    return row if col == 0 and row > node.start_point[0] else row + 1


def _comment_ranges(node: Node) -> list[tuple[int, int]]:
    """Byte ranges of every comment inside node."""
    out, stack = [], [node]
    while stack:
        n = stack.pop()
        if n.type == "comment":
            out.append((n.start_byte, n.end_byte))
        else:
            stack.extend(n.children)
    return sorted(out)


def _value_text(node: Node) -> str:
    """The value's source text without comments, whitespace collapsed and clipped.

    Comments are dropped so that editing a comment inside a multi-line value is not mistaken for
    the value changing (Phase 2 compares values across commits).
    """
    raw = node.text or b""
    parts, pos = [], node.start_byte
    for start, end in _comment_ranges(node):
        parts.append(raw[pos - node.start_byte : start - node.start_byte])
        pos = end
    parts.append(raw[pos - node.start_byte :])
    text = b"".join(parts).decode("utf-8", errors="replace")
    return " ".join(text.split())[:_MAX_VALUE_CHARS]


def _references_constant(value: Node) -> bool:
    if value.type == "identifier":
        return bool(_UPPER_RE.match(_text(value)))
    if value.type == "attribute":  # settings.TIMEOUT
        return bool(_UPPER_RE.match(_text(value.child_by_field_name("attribute"))))
    return False


def _assignment_targets(target: Node) -> list[Node]:
    """Plain names assigned by `target`; `A, B = ...` gives both, `obj.X = ...` gives none."""
    if target.type == "identifier":
        return [target]
    if target.type in ("pattern_list", "tuple_pattern", "list_pattern"):
        return [n for c in target.named_children for n in _assignment_targets(c)]
    return []


class _Walker:
    def __init__(self, repo: str, path: str):
        self.repo = repo
        self.path = path
        self.file_id = make_id(repo, "file", path)
        self.entities: dict[str, CodeEntity] = {}  # by id; dicts keep insertion order

    def run(self, root: Node, data: bytes) -> ParsedFile:
        self._add(
            self.file_id,
            EntityKind.FILE,
            PurePosixPath(self.path).name,
            PurePosixPath(self.path).name,
            1,
            _line_count(data),
            None,
        )
        self._visit_children(root, scope=[], parent_id=self.file_id)
        return ParsedFile(self.path, tuple(self.entities.values()), root.has_error)

    def _add(self, id_, kind, name, qualified, start, end, parent_id, value=None) -> None:
        if id_ not in self.entities:
            self.entities[id_] = CodeEntity(
                id_, self.repo, kind, name, qualified, self.path, start, end, parent_id, value
            )

    def _visit_children(self, node: Node, scope: list[str], parent_id: str) -> None:
        for child in node.children:
            self._visit(child, scope, parent_id)

    def _visit(self, node: Node, scope: list[str], parent_id: str) -> None:
        if node.type in ("class_definition", "function_definition"):
            self._definition(node, node, scope, parent_id)
        elif node.type == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is not None:
                self._definition(inner, node, scope, parent_id)
        elif node.type == "assignment" and not scope:
            self._module_constant(node)
            self._visit_children(node, scope, parent_id)
        else:
            self._visit_children(node, scope, parent_id)

    def _definition(self, node: Node, span: Node, scope: list[str], parent_id: str) -> None:
        name = _text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        if not name:  # too broken to name; still look inside for recoverable definitions
            if body is not None:
                self._visit_children(body, scope, parent_id)
            return
        qualified = ".".join([*scope, name])
        if node.type == "class_definition":
            kind, id_ = EntityKind.CLASS, make_id(self.repo, "cls", f"{self.path}::{qualified}")
        else:
            kind, id_ = EntityKind.FUNCTION, make_id(self.repo, "fn", f"{self.path}::{qualified}")
        self._add(id_, kind, name, qualified, span.start_point[0] + 1, _end_line(span), parent_id)
        if kind is EntityKind.FUNCTION:
            self._default_args(node, qualified, id_)
        if body is not None:
            self._visit_children(body, [*scope, name], id_)

    def _default_args(self, fn: Node, fn_qualified: str, fn_id: str) -> None:
        params = fn.child_by_field_name("parameters")
        if params is None:
            return
        for param in params.named_children:
            if param.type not in ("default_parameter", "typed_default_parameter"):
                continue
            value = param.child_by_field_name("value")
            name = _text(param.child_by_field_name("name"))
            if not name or value is None or not _references_constant(value):
                continue
            self._add(
                make_id(self.repo, "cfg", name),
                EntityKind.CONFIG_KEY,
                name,
                f"{fn_qualified}.{name}",
                param.start_point[0] + 1,
                _end_line(param),
                fn_id,
                _value_text(value),
            )

    def _module_constant(self, node: Node) -> None:
        # `X: int` with no value declares a name but sets nothing.
        right = node.child_by_field_name("right")
        if right is None:
            return
        # In `A = B = 2` both names get "2", not "B = 2".
        while right.type == "assignment" and right.child_by_field_name("right") is not None:
            right = right.child_by_field_name("right")
        left = node.child_by_field_name("left")
        # Report the whole statement's lines, not just this (possibly chained) assignment.
        stmt = node
        while stmt.parent is not None and stmt.parent.type in _STATEMENT_WRAPPERS:
            stmt = stmt.parent
        for target in _assignment_targets(left) if left is not None else []:
            name = _text(target)
            if _UPPER_RE.match(name):
                self._add(
                    make_id(self.repo, "cfg", name),
                    EntityKind.CONFIG_KEY,
                    name,
                    name,
                    stmt.start_point[0] + 1,
                    _end_line(stmt),
                    self.file_id,
                    _value_text(right),
                )


@dataclass
class _Definition:
    """A class, function or scope a query found, before it becomes an entity. A scope (kind
    None) names what is inside it but is no entity itself."""

    kind: EntityKind | None
    name: str
    node: Node
    owner: str | None = None  # the type a method declared outside it belongs to (Go)
    qualified: str = ""
    id: str = ""
    parent: "_Definition | None" = None


def _name_text(node: Node) -> str:
    """A definition's name, whitespace collapsed; a quoted object key loses its quotes."""
    text = _text(node)
    if node.type == "string" and len(text) >= 2:
        text = text[1:-1]
    return " ".join(text.split())


_KIND_BY_CAPTURE = {"class": EntityKind.CLASS, "function": EntityKind.FUNCTION, "scope": None}


class _QueryWalker:
    """Entities from the matches of a QueryLanguage's query (see whycode/code/languages.py)."""

    def __init__(self, repo: str, path: str, lang: QueryLanguage):
        self.repo = repo
        self.path = path
        self.lang = lang
        self.file_id = make_id(repo, "file", path)

    def run(self, root: Node, data: bytes) -> ParsedFile:
        spans: dict[tuple[int, int], _Definition] = {}
        configs: list[tuple[Node, Node, Node]] = []  # (statement, name, value)
        defaults: list[tuple[Node, Node, Node]] = []  # (parameter, name, value)
        for _, caps in QueryCursor(self.lang.query).matches(root):
            name = caps["name"][0]
            value = caps["value"][0] if "value" in caps else None
            if "config" in caps:
                if value is not None:
                    configs.append((caps["config"][0], name, value))
            elif "default" in caps:
                if value is not None:
                    defaults.append((caps["default"][0], name, value))
            elif capture := next((c for c in _KIND_BY_CAPTURE if c in caps), None):
                node = caps[capture][0]
                owner = _name_text(caps["owner"][0]) if "owner" in caps else None
                if text := _name_text(name):
                    spans.setdefault(
                        (node.start_byte, node.end_byte),
                        _Definition(_KIND_BY_CAPTURE[capture], text, node, owner),
                    )
        defs = self._nest(
            sorted(spans.values(), key=lambda d: (d.node.start_byte, -d.node.end_byte))
        )
        classes = {d.qualified: d for d in defs if d.kind is EntityKind.CLASS}

        found = []
        for d in defs:
            if d.kind is None:
                continue
            if d.owner is not None:
                parent_id = classes[d.owner].id if d.owner in classes else self.file_id
            else:
                parent_id = self._parent_id(d.parent, classes)
            found.append(
                (d.node, self._entity(d.id, d.kind, d.name, d.qualified, d.node, parent_id))
            )
        for stmt, name_node, value in configs:
            name = _text(name_node)
            if value.type in self.lang.code_values or not self._is_config_name(name):
                continue
            holder = self._innermost(stmt, defs)
            entity = self._entity(
                make_id(self.repo, "cfg", name),
                EntityKind.CONFIG_KEY,
                name,
                f"{holder.qualified}.{name}" if holder else name,
                stmt,
                self._parent_id(holder, classes),
                _value_text(value),
            )
            found.append((stmt, entity))
        for param, name_node, value in defaults:
            owner = self._owner(param, defs)
            if owner is None or not self._references_constant(value):
                continue
            name = _text(name_node)
            entity = self._entity(
                make_id(self.repo, "cfg", name),
                EntityKind.CONFIG_KEY,
                name,
                f"{owner.qualified}.{name}",
                param,
                owner.id,
                _value_text(value),
            )
            found.append((param, entity))

        base = PurePosixPath(self.path).name
        entities = {
            self.file_id: CodeEntity(
                self.file_id,
                self.repo,
                EntityKind.FILE,
                base,
                base,
                self.path,
                1,
                _line_count(data),
                None,
            )
        }
        # Source order, outer before inner; an id seen twice (a getter and its setter) keeps the
        # first.
        for _, e in sorted(found, key=lambda f: (f[0].start_byte, -f[0].end_byte)):
            entities.setdefault(e.id, e)
        return ParsedFile(self.path, tuple(entities.values()), root.has_error)

    def _entity(self, id_, kind, name, qualified, node, parent_id, value=None) -> CodeEntity:
        return CodeEntity(
            id_,
            self.repo,
            kind,
            name,
            qualified,
            self.path,
            node.start_point[0] + 1,
            _end_line(node),
            parent_id,
            value,
        )

    def _nest(self, defs: list[_Definition]) -> list[_Definition]:
        """Give each definition (sorted by start, outer first) its qualified name and the
        innermost definition or scope around it. A method with an owner is "Owner.name"."""
        stack: list[_Definition] = []
        for d in defs:
            while stack and stack[-1].node.end_byte < d.node.end_byte:
                stack.pop()
            d.parent = stack[-1] if stack else None
            if d.owner is not None:
                d.qualified = f"{d.owner}.{d.name}"
            else:
                d.qualified = f"{d.parent.qualified}.{d.name}" if d.parent else d.name
            if d.kind is not None:
                prefix = "cls" if d.kind is EntityKind.CLASS else "fn"
                d.id = make_id(self.repo, prefix, f"{self.path}::{d.qualified}")
            stack.append(d)
        return defs

    def _parent_id(self, parent: _Definition | None, classes: dict[str, _Definition]) -> str:
        """The entity something belongs to: its definition; through a scope, the class the scope
        names (Rust's `impl Router` gives the Router struct), else what holds the scope; at the
        top, the file."""
        while parent is not None and parent.kind is None:
            named = classes.get(parent.qualified)
            if named is not None:
                return named.id
            parent = parent.parent
        return parent.id if parent is not None else self.file_id

    @staticmethod
    def _innermost(node: Node, defs: list[_Definition]) -> _Definition | None:
        """The innermost definition or scope strictly around `node` (defs sorted outer first)."""
        around = None
        for d in defs:
            span = (d.node.start_byte, d.node.end_byte)
            inside = span[0] <= node.start_byte and node.end_byte <= span[1]
            if inside and span != (node.start_byte, node.end_byte):
                around = d
        return around

    @staticmethod
    def _owner(param: Node, defs: list[_Definition]) -> _Definition | None:
        """The function whose own parameter list holds `param`: the definition itself
        (`function f(x = A)`) or the function that is its value (`const f = (x = A) => x`).
        A default in a callback inside f is not f's."""
        params = param.parent
        fn = params.parent if params is not None else None
        if fn is None:
            return None
        holders = [fn] if fn.parent is None else [fn, fn.parent]
        return next((d for d in defs if d.kind is EntityKind.FUNCTION and d.node in holders), None)

    def _is_config_name(self, name: str) -> bool:
        if self.lang.config_upper_only:
            return bool(_UPPER_RE.match(name))
        return any(c.isalpha() for c in name)  # not Go's blank `_`

    def _is_constant_name(self, text: str) -> bool:
        if self.lang.ref_upper_only:
            return bool(_UPPER_RE.match(text))
        return bool(text) and (text[0].isalpha() or text[0] == "_")

    def _references_constant(self, value: Node) -> bool:
        lang = self.lang
        if value.type in lang.constant_types:
            return True
        if value.type in lang.ref_types:
            return self._is_constant_name(_text(value))
        if value.type not in lang.member_name_field:
            return False
        field = lang.member_name_field[value.type]
        named = value.named_children
        member = value.child_by_field_name(field) if field else (named[-1] if named else None)
        if member is None:
            return False
        return member.type in lang.constant_types or self._is_constant_name(_text(member))
