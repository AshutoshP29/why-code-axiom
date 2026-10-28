import pytest

from whycode.extract.entities import (
    EntityKind,
    UnsupportedFileError,
    is_supported,
    normalize_path,
    parse_file,
)
from whycode.ids import make_id

REPO = "psf/requests"
PATH = "src/requests/adapters.py"

# Line numbers matter: tests below assert them.
ADAPTERS = '''\
"""Transport adapters."""
import os

DEFAULT_POOLSIZE = 10
DEFAULT_RETRIES: int = 0
DEFAULT_POOL_TIMEOUT = None
CONNECT_TIMEOUT = READ_TIMEOUT = 30
logger = os.getenv("X")
T = TypeVar("T")

try:
    PROXY_FALLBACK = "socks"
except ImportError:
    PROXY_FALLBACK = None


class BaseAdapter:
    """The Base Transport Adapter"""

    LOCAL_ONLY = 1

    def send(self, request, stream=False, timeout=None, verify=True, cert=None):
        raise NotImplementedError

    class Options:
        def merge(self, other):
            def pick(a, b):
                return a or b

            return pick(self, other)


class HTTPAdapter(BaseAdapter):
    def __init__(
        self,
        pool_connections=DEFAULT_POOLSIZE,
        max_retries: int = DEFAULT_RETRIES,
        pool_block=False,
        hooks=None if False else {},
        callback=lambda x=5: x,
        backoff=-0.5,
        *args,
        **kwargs,
    ):
        self.max_retries = max_retries

    @property
    def closed(self):
        return False

    @closed.setter
    def closed(self, value):
        pass


async def fetch_all(urls, limit=settings.MAX_CONCURRENCY, mode="fast", factory=dict):
    return [u for u in urls]
'''


@pytest.fixture(scope="module")
def parsed():
    return parse_file(REPO, PATH, ADAPTERS)


def by_qualified(parsed, kind):
    return {e.qualified_name: e for e in parsed.of_kind(kind)}


def lines(entity):
    return (entity.start_line, entity.end_line)


def test_file_entity_comes_first_and_spans_the_file(parsed):
    f = parsed.entities[0]
    assert f.kind is EntityKind.FILE
    assert f.id == make_id(REPO, "file", PATH) == "psf/requests#file:src/requests/adapters.py"
    assert (f.name, f.path, f.parent_id) == ("adapters.py", PATH, None)
    assert lines(f) == (1, ADAPTERS.count("\n"))
    assert not parsed.has_syntax_errors


def test_classes_including_nested(parsed):
    classes = by_qualified(parsed, EntityKind.CLASS)
    assert set(classes) == {"BaseAdapter", "BaseAdapter.Options", "HTTPAdapter"}
    assert lines(classes["BaseAdapter"]) == (17, 30)
    assert lines(classes["BaseAdapter.Options"]) == (25, 30)
    assert lines(classes["HTTPAdapter"]) == (33, 53)
    assert classes["BaseAdapter.Options"].name == "Options"
    assert classes["BaseAdapter.Options"].parent_id == classes["BaseAdapter"].id
    assert classes["HTTPAdapter"].id == "psf/requests#cls:src/requests/adapters.py::HTTPAdapter"


def test_functions_methods_and_nested_functions(parsed):
    fns = by_qualified(parsed, EntityKind.FUNCTION)
    assert set(fns) == {
        "BaseAdapter.send",
        "BaseAdapter.Options.merge",
        "BaseAdapter.Options.merge.pick",
        "HTTPAdapter.__init__",
        "HTTPAdapter.closed",
        "fetch_all",
    }
    assert lines(fns["BaseAdapter.send"]) == (22, 23)
    assert lines(fns["BaseAdapter.Options.merge"]) == (26, 30)
    assert lines(fns["BaseAdapter.Options.merge.pick"]) == (27, 28)
    assert lines(fns["HTTPAdapter.__init__"]) == (34, 45)
    assert lines(fns["fetch_all"]) == (56, 57)
    assert fns["BaseAdapter.Options.merge.pick"].parent_id == fns["BaseAdapter.Options.merge"].id
    assert fns["fetch_all"].parent_id == parsed.entities[0].id
    assert (
        fns["HTTPAdapter.__init__"].id
        == "psf/requests#fn:src/requests/adapters.py::HTTPAdapter.__init__"
    )


def test_decorated_definition_starts_at_decorator_and_duplicates_keep_first(parsed):
    closed = [e for e in parsed.entities if e.qualified_name == "HTTPAdapter.closed"]
    assert len(closed) == 1
    assert lines(closed[0]) == (47, 49)  # the getter, from "@property"


def test_module_level_uppercase_constants(parsed):
    file_id = parsed.entities[0].id
    module_cfg = {
        e.name: e for e in parsed.of_kind(EntityKind.CONFIG_KEY) if e.parent_id == file_id
    }
    assert set(module_cfg) == {
        "DEFAULT_POOLSIZE",
        "DEFAULT_RETRIES",
        "DEFAULT_POOL_TIMEOUT",
        "CONNECT_TIMEOUT",
        "READ_TIMEOUT",
        "PROXY_FALLBACK",
    }
    assert lines(module_cfg["DEFAULT_RETRIES"]) == (5, 5)
    assert lines(module_cfg["READ_TIMEOUT"]) == (7, 7)
    assert lines(module_cfg["PROXY_FALLBACK"]) == (12, 12)  # first assignment wins
    assert module_cfg["DEFAULT_POOLSIZE"].id == "psf/requests#cfg:DEFAULT_POOLSIZE"
    assert module_cfg["DEFAULT_POOLSIZE"].qualified_name == "DEFAULT_POOLSIZE"


def test_class_level_and_lowercase_and_single_letter_names_are_not_constants(parsed):
    names = {e.name for e in parsed.of_kind(EntityKind.CONFIG_KEY)}
    assert "LOCAL_ONLY" not in names
    assert "logger" not in names
    assert "T" not in names


def test_default_arguments_with_literal_or_constant_values(parsed):
    cfg = by_qualified(parsed, EntityKind.CONFIG_KEY)
    fns = by_qualified(parsed, EntityKind.FUNCTION)
    expected = {
        "BaseAdapter.send.stream",
        "BaseAdapter.send.timeout",
        "BaseAdapter.send.verify",
        "BaseAdapter.send.cert",
        "HTTPAdapter.__init__.pool_connections",
        "HTTPAdapter.__init__.max_retries",
        "HTTPAdapter.__init__.pool_block",
        "HTTPAdapter.__init__.backoff",
        "fetch_all.limit",
        "fetch_all.mode",
    }
    assert expected <= set(cfg)
    max_retries = cfg["HTTPAdapter.__init__.max_retries"]
    assert max_retries.id == "psf/requests#cfg:max_retries"
    assert max_retries.parent_id == fns["HTTPAdapter.__init__"].id
    assert lines(max_retries) == (37, 37)


def test_complex_defaults_lambda_params_and_splats_are_skipped(parsed):
    names = {e.name for e in parsed.of_kind(EntityKind.CONFIG_KEY)}
    assert not names & {"hooks", "callback", "x", "factory", "args", "kwargs", "self"}


def test_ids_are_unique(parsed):
    ids = [e.id for e in parsed.entities]
    assert len(ids) == len(set(ids))
    assert all(e.repo == REPO and e.path == PATH for e in parsed.entities)


def test_parsing_is_deterministic():
    assert parse_file(REPO, PATH, ADAPTERS) == parse_file(REPO, PATH, ADAPTERS.encode())


def test_same_default_arg_twice_in_a_file_is_one_entity():
    src = "def a(timeout=1):\n    pass\n\n\ndef b(timeout=2):\n    pass\n"
    cfg = parse_file(REPO, "x.py", src).of_kind(EntityKind.CONFIG_KEY)
    assert [(c.qualified_name, c.start_line) for c in cfg] == [("a.timeout", 1)]


def test_empty_file_gives_only_the_file_entity():
    parsed = parse_file(REPO, "pkg/__init__.py", "")
    assert [e.kind for e in parsed.entities] == [EntityKind.FILE]
    assert lines(parsed.entities[0]) == (1, 1)
    assert not parsed.has_syntax_errors


def test_syntax_error_keeps_what_was_recovered():
    src = "def ok():\n    return 1\n\n\ndef broken(:\n    pass\n\n\nclass Fine:\n    pass\n"
    parsed = parse_file(REPO, "bad.py", src)
    assert parsed.has_syntax_errors
    assert "ok" in by_qualified(parsed, EntityKind.FUNCTION)
    assert lines(by_qualified(parsed, EntityKind.CLASS)["Fine"]) == (9, 10)


def test_garbage_input_does_not_raise():
    parsed = parse_file(REPO, "junk.py", b"\xff\xfe def ((( class :::\n\x00")
    assert parsed.has_syntax_errors
    assert parsed.entities[0].kind is EntityKind.FILE


def test_crlf_line_endings_give_the_same_lines():
    src = "class A:\r\n    def f(self):\r\n        pass\r\n"
    fns = by_qualified(parse_file(REPO, "a.py", src), EntityKind.FUNCTION)
    assert lines(fns["A.f"]) == (2, 3)


@pytest.mark.parametrize("path", ["README.md", "setup.cfg", "lib/x.pyc", "Makefile", "a.pyi"])
def test_unsupported_file_types_rejected(path):
    assert not is_supported(path)
    with pytest.raises(UnsupportedFileError):
        parse_file(REPO, path, "x = 1")


def test_windows_and_dot_paths_are_normalized():
    assert normalize_path("src\\requests\\api.py") == "src/requests/api.py"
    assert normalize_path("./src/requests/api.py") == "src/requests/api.py"
    parsed = parse_file(REPO, "src\\requests\\api.py", "")
    assert parsed.entities[0].id == "psf/requests#file:src/requests/api.py"


@pytest.mark.parametrize("bad", ["/abs/x.py", "C:/x.py", "../x.py", "a/../../x.py", "", "."])
def test_paths_outside_the_repo_rejected(bad):
    with pytest.raises(ValueError):
        normalize_path(bad)
