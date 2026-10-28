import pytest

from tests.unit.test_code_index import REPO, fetched
from whycode.code.affects import resolve_affects
from whycode.code.entities import EntityKind
from whycode.code.index import build_pr_code_index
from whycode.extract.models import Affected


@pytest.fixture(scope="module")
def index():
    return build_pr_code_index(fetched(), REPO, 1565)


def check(index, *items):
    return resolve_affects([Affected(**i) for i in items], index)


def test_changed_file_is_kept_with_todays_path(index):
    r = check(index, {"kind": "file", "path": "fixture/utils.py"})
    assert [(k.kind, k.id) for k in r.kept] == [
        (EntityKind.FILE, "test/fixture#file:lib/fixture/utils.py")
    ]


def test_file_the_pr_did_not_change_is_dropped(index):
    r = check(index, {"kind": "file", "path": "setup.py"})
    assert r.kept == [] and r.dropped[0].reason == "'setup.py' was not changed in this PR"


def test_exact_method_name_is_kept(index):
    r = check(
        index, {"kind": "function", "path": "src/fixture/compat.py", "name": "Detector.detect"}
    )
    assert r.kept[0].id == "test/fixture#fn:src/fixture/compat.py::Detector.detect"
    assert r.kept[0].note is None


def test_module_prefixed_name_is_kept_with_a_note(index):
    item = {"kind": "function", "path": "src/fixture/compat.py", "name": "fixture.compat.detect"}
    r = check(index, item)
    assert r.kept[0].name == "detect" and r.kept[0].note == "module prefix dropped"


def test_ambiguous_short_name_is_dropped_not_guessed(index):
    # "detect" exactly is the module function; "run.detect" only shares the short name with two.
    r = check(index, {"kind": "function", "path": "src/fixture/compat.py", "name": "run.detect"})
    assert r.kept == []
    assert r.dropped[0].reason.startswith("ambiguous: 2 definitions named 'detect'")


def test_unique_short_name_is_kept(index):
    r = check(index, {"kind": "function", "path": "fixture/utils.py", "name": "helpers.to_text"})
    assert r.kept[0].id == "test/fixture#fn:lib/fixture/utils.py::to_text"


def test_class_named_as_a_function_is_kept_as_a_class(index):
    r = check(index, {"kind": "function", "path": "src/fixture/compat.py", "name": "Detector"})
    assert r.kept[0].kind is EntityKind.CLASS and r.kept[0].note == "is a class"
    assert r.kept[0].id == "test/fixture#cls:src/fixture/compat.py::Detector"


def test_invented_function_is_dropped(index):
    r = check(
        index, {"kind": "function", "path": "src/fixture/compat.py", "name": "guess_encoding"}
    )
    assert (
        r.dropped[0].reason
        == "no function or class named 'guess_encoding' in src/fixture/compat.py"
    )


def test_config_key_module_constant_and_parameter(index):
    r = check(
        index,
        {"kind": "config", "path": "src/fixture/compat.py", "name": "MAX_BYTES"},
        {"kind": "config", "path": "fixture/utils.py", "name": "encoding"},
    )
    assert [k.id for k in r.kept] == ["test/fixture#cfg:MAX_BYTES", "test/fixture#cfg:encoding"]


def test_invented_config_key_is_dropped(index):
    r = check(index, {"kind": "config", "path": "src/fixture/compat.py", "name": "TIMEOUT"})
    assert r.dropped[0].reason == "no config key named 'TIMEOUT' in src/fixture/compat.py"


def test_code_name_in_a_non_python_file_is_dropped(index):
    r = check(index, {"kind": "function", "path": "README.md", "name": "install"})
    assert r.dropped[0].reason == "'README.md' is not parsed Python code"


def test_missing_name_is_dropped(index):
    r = check(index, {"kind": "function", "path": "src/fixture/compat.py"})
    assert r.dropped[0].reason == "no function name given"


def test_missing_code_says_to_fetch_again():
    store = fetched()
    del store.rows[(REPO, "blob", "c0ffee02")]
    idx = build_pr_code_index(store, REPO, 1565)
    r = resolve_affects([Affected(kind="function", path="fixture/utils.py", name="to_text")], idx)
    assert r.dropped[0].reason == "code not fetched; run fetch_pr again"


def test_duplicates_are_kept_once(index):
    r = check(
        index,
        {"kind": "file", "path": "fixture/compat.py"},
        {"kind": "file", "path": "src/fixture/compat.py"},
    )
    assert len(r.kept) == 1


def test_module_names_for_a_file():
    from whycode.code.affects import module_names

    assert module_names("src/requests/compat.py") == {
        "compat",
        "requests.compat",
        "src.requests.compat",
    }
    assert module_names("requests/__init__.py") == {"requests"}
    assert module_names("README.md", None) == set()


def test_prefix_matching_todays_module_path_is_accepted(index):
    # lib/fixture/utils.py today, fixture/utils.py in the PR: both module spellings work.
    for name in ("lib.fixture.utils.to_text", "fixture.utils.to_text"):
        r = check(index, {"kind": "function", "path": "fixture/utils.py", "name": name})
        assert r.kept[0].name == "to_text" and r.kept[0].note == "module prefix dropped", name


def test_class_kind_is_accepted(index):
    r = check(index, {"kind": "class", "path": "src/fixture/compat.py", "name": "Detector"})
    assert r.kept[0].kind is EntityKind.CLASS and r.kept[0].note is None


def test_function_named_as_a_class_is_kept_as_a_function(index):
    r = check(index, {"kind": "class", "path": "fixture/utils.py", "name": "to_text"})
    assert r.kept[0].kind is EntityKind.FUNCTION and r.kept[0].note == "is a function"
