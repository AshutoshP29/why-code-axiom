"""Code entities in one source file, parsed with tree-sitter: File, Class, Function, ConfigKey.

Python is read by the walker below. JavaScript, and any language added to
whycode/code/languages.py, is read by running that language's query (_QueryWalker), with the same
rules wherever the language has the construct.

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

JavaScript, as the query in languages.py finds it:
- Classes are declarations and named class expressions; `const Widget = class {}` is "Widget".
- Functions are declarations, methods (getters, setters and the constructor included), and
  functions assigned to a name: `const f = () => {}`, `res.send = function send() {}` ("send"),
  `{ close: function () {} }` ("close"). Callbacks passed as arguments are not entities.
- ConfigKeys are top-level `const`/`let`/`var` declarations, exported or not, with an
  UPPER_CASE name and a value that is not a function or class; and parameter defaults that
  reference a constant (`retries = MAX_RETRIES`, `timeout = config.TIMEOUT`). Class fields
  (`static LIMIT = 5`) are not, as class-level names are not for Python.
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
    """A class or function a query found, before it becomes an entity."""

    kind: EntityKind
    name: str
    node: Node
    qualified: str = ""
    id: str = ""
    parent_id: str = ""


def _name_text(node: Node) -> str:
    """A definition's name, whitespace collapsed; a quoted object key loses its quotes."""
    text = _text(node)
    if node.type == "string" and len(text) >= 2:
        text = text[1:-1]
    return " ".join(text.split())


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
            if "config" in caps and value is not None:
                configs.append((caps["config"][0], name, value))
            elif "default" in caps and value is not None:
                defaults.append((caps["default"][0], name, value))
            elif "class" in caps or "function" in caps:
                kind = EntityKind.CLASS if "class" in caps else EntityKind.FUNCTION
                node = caps["class" if kind is EntityKind.CLASS else "function"][0]
                if text := _name_text(name):
                    spans.setdefault(
                        (node.start_byte, node.end_byte), _Definition(kind, text, node)
                    )
        defs = self._nest(
            sorted(spans.values(), key=lambda d: (d.node.start_byte, -d.node.end_byte))
        )

        found = [
            (d.node, self._entity(d.id, d.kind, d.name, d.qualified, d.node, d.parent_id))
            for d in defs
        ]
        for stmt, name_node, value in configs:
            name = _text(name_node)
            if _UPPER_RE.match(name) and value.type not in self.lang.code_values:
                id_ = make_id(self.repo, "cfg", name)
                cfg = EntityKind.CONFIG_KEY
                found.append(
                    (
                        stmt,
                        self._entity(id_, cfg, name, name, stmt, self.file_id, _value_text(value)),
                    )
                )
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
        """Give each definition (sorted by start, outer first) its qualified name and parent: the
        innermost definition around it, else the file."""
        stack: list[_Definition] = []
        for d in defs:
            while stack and stack[-1].node.end_byte < d.node.end_byte:
                stack.pop()
            parent = stack[-1] if stack else None
            d.qualified = f"{parent.qualified}.{d.name}" if parent else d.name
            d.parent_id = parent.id if parent else self.file_id
            prefix = "cls" if d.kind is EntityKind.CLASS else "fn"
            d.id = make_id(self.repo, prefix, f"{self.path}::{d.qualified}")
            stack.append(d)
        return defs

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

    def _references_constant(self, value: Node) -> bool:
        if value.type == "identifier":
            return bool(_UPPER_RE.match(_text(value)))
        field = self.lang.member_name_field.get(value.type)
        return field is not None and bool(_UPPER_RE.match(_text(value.child_by_field_name(field))))
