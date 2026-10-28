"""Check what an extracted decision says it affects against the code the PR really touched.

An item is kept only if it is real:
- a file must be one the PR changed (by its PR path, old name, today's path, or a unique tail);
- a function or class must exist in that file's parsed code;
- a config key must be one the parser found in that file.
Kept items carry their graph id. Everything else is dropped with a reason, never guessed.
"""

from dataclasses import dataclass, field

from whycode.code.entities import CodeEntity, EntityKind
from whycode.code.index import PrCodeIndex
from whycode.extract.models import Affected


@dataclass(frozen=True)
class ResolvedAffect:
    kind: EntityKind
    id: str
    path: str  # today's path when known
    name: str | None  # qualified name for classes, functions and config keys
    note: str | None = None  # how a loose name was matched, e.g. "matched by short name"


@dataclass(frozen=True)
class DroppedAffect:
    item: Affected
    reason: str


@dataclass
class AffectsCheck:
    kept: list[ResolvedAffect] = field(default_factory=list)
    dropped: list[DroppedAffect] = field(default_factory=list)


_CODE_KINDS = (EntityKind.FUNCTION, EntityKind.CLASS)


def module_names(*paths: str | None) -> set[str]:
    """Every dotted module name a file can be written as: src/requests/compat.py gives
    "compat", "requests.compat" and "src.requests.compat"."""
    names = set()
    for path in paths:
        if path and path.endswith(".py"):
            parts = path.removesuffix(".py").split("/")
            if parts[-1] == "__init__":
                parts = parts[:-1]
            names.update(".".join(parts[i:]) for i in range(len(parts)))
    return names


def _match_code(
    name: str, entities: list[CodeEntity], modules: set[str]
) -> tuple[CodeEntity | None, str | None]:
    """Find one function or class for a name. Returns (entity, note) or (None, reason)."""
    exact = [e for e in entities if e.qualified_name == name]
    if len(exact) == 1:
        return exact[0], None
    # "requests.compat.detect": the parser never includes the module, so strip it, but only when
    # the prefix really is this file's module. "run.detect" must not silently become "detect".
    prefixed = [
        e
        for e in entities
        if name.endswith("." + e.qualified_name)
        and name.removesuffix("." + e.qualified_name) in modules
    ]
    if len(prefixed) == 1:
        return prefixed[0], "module prefix dropped"
    short = name.rsplit(".", 1)[-1]
    by_short = [e for e in entities if e.name == short]
    if len(by_short) == 1:
        return by_short[0], "matched by short name"
    if len(by_short) > 1:
        options = ", ".join(sorted(e.qualified_name for e in by_short))
        return None, f"ambiguous: {len(by_short)} definitions named {short!r} ({options})"
    return None, f"no function or class named {name!r}"


def _match_config(name: str, entities: list[CodeEntity]) -> CodeEntity | None:
    short = name.rsplit(".", 1)[-1]
    for test in (lambda e: e.qualified_name == name, lambda e: e.name == short):
        hits = {
            e.id: e for e in entities if test(e)
        }  # config ids are repo-wide: same id = same key
        if len(hits) == 1:
            return next(iter(hits.values()))
    return None


def resolve_affects(items: list[Affected], index: PrCodeIndex) -> AffectsCheck:
    out = AffectsCheck()
    seen: set[str] = set()

    def keep(r: ResolvedAffect) -> None:
        if r.id not in seen:
            seen.add(r.id)
            out.kept.append(r)

    for item in items:
        f = index.find_file(item.path)
        if f is None:
            out.dropped.append(DroppedAffect(item, f"{item.path!r} was not changed in this PR"))
            continue
        if item.kind == "file":
            keep(ResolvedAffect(EntityKind.FILE, index.file_id(f), f.graph_path, None))
            continue
        if not item.name:
            out.dropped.append(DroppedAffect(item, f"no {item.kind} name given"))
            continue
        parsed = index.parsed.get(f.pr_path)
        if parsed is None:
            why = (
                "code not fetched; run fetch_pr again"
                if f.pr_path in index.missing_code
                else f"{f.pr_path!r} is not parsed Python code"
            )
            out.dropped.append(DroppedAffect(item, why))
            continue
        if item.kind == "config":
            hit = _match_config(item.name, parsed.of_kind(EntityKind.CONFIG_KEY))
            if hit is None:
                reason = f"no config key named {item.name!r} in {f.graph_path}"
                out.dropped.append(DroppedAffect(item, reason))
            else:
                keep(
                    ResolvedAffect(EntityKind.CONFIG_KEY, hit.id, f.graph_path, hit.qualified_name)
                )
            continue
        code = [e for e in parsed.entities if e.kind in _CODE_KINDS]
        hit, note = _match_code(item.name, code, module_names(f.pr_path, f.current_path))
        if hit is None:
            out.dropped.append(DroppedAffect(item, f"{note} in {f.graph_path}"))
            continue
        if item.kind == "function" and hit.kind is EntityKind.CLASS:
            note = "is a class" if note is None else f"{note}; is a class"
        keep(ResolvedAffect(hit.kind, hit.id, f.graph_path, hit.qualified_name, note))
    return out
