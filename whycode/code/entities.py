"""Code entities in one Python file, parsed with tree-sitter: File, Class, Function, ConfigKey.

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
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from whycode.ids import make_id, normalize_repo

SUPPORTED_SUFFIXES = frozenset({".py"})

_LANGUAGE = Language(tspython.language())
# Two characters or more, so single-letter TypeVars ("T = TypeVar('T')") are not config.
_UPPER_RE = re.compile(r"^_*[A-Z][A-Z0-9_]+$")
_STATEMENT_WRAPPERS = frozenset({"assignment", "expression_statement"})


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


@dataclass(frozen=True)
class ParsedFile:
    path: str
    entities: tuple[CodeEntity, ...]  # the File first, then in source order
    has_syntax_errors: bool

    def of_kind(self, kind: EntityKind) -> list[CodeEntity]:
        return [e for e in self.entities if e.kind is kind]


class UnsupportedFileError(ValueError):
    pass


def is_supported(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).suffix in SUPPORTED_SUFFIXES


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
    """Parse one Python file into its entities. Raises UnsupportedFileError for other types."""
    path = normalize_path(path)
    if not is_supported(path):
        raise UnsupportedFileError(f"not a Python file: {path!r}")
    data = source.encode("utf-8") if isinstance(source, str) else source
    tree = Parser(_LANGUAGE).parse(data)
    return _Walker(normalize_repo(repo), path).run(tree.root_node, data)


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None and node.text else ""


def _end_line(node: Node) -> int:
    # A node that ends at column 0 stops at the start of the next line, not on it.
    row, col = node.end_point
    return row if col == 0 and row > node.start_point[0] else row + 1


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
        line_count = data.count(b"\n") + (0 if not data or data.endswith(b"\n") else 1)
        self._add(
            self.file_id,
            EntityKind.FILE,
            PurePosixPath(self.path).name,
            PurePosixPath(self.path).name,
            1,
            max(1, line_count),
            None,
        )
        self._visit_children(root, scope=[], parent_id=self.file_id)
        return ParsedFile(self.path, tuple(self.entities.values()), root.has_error)

    def _add(self, id_, kind, name, qualified, start, end, parent_id) -> None:
        if id_ not in self.entities:
            self.entities[id_] = CodeEntity(
                id_, self.repo, kind, name, qualified, self.path, start, end, parent_id
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
            )

    def _module_constant(self, node: Node) -> None:
        # `X: int` with no value declares a name but sets nothing.
        if node.child_by_field_name("right") is None:
            return
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
                )
