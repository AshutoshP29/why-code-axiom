import pytest

from tests.fakes import FakeGitHub, MemoryRawStore, load_github_fixture
from whycode.code.entities import EntityKind
from whycode.code.index import build_pr_code_index, map_to_current
from whycode.ingest.fetch_pr import fetch_pr
from whycode.ingest.github import GitHubClient

REPO = "test/fixture"


def fetched(routes=None):
    store = MemoryRawStore()
    gh_routes = routes or load_github_fixture("pr_1565.json")
    with GitHubClient("t", transport=FakeGitHub(gh_routes).transport()) as gh:
        fetch_pr(gh, store, REPO, 1565)
    return store


@pytest.mark.parametrize(
    "path, expected",
    [
        ("README.md", "README.md"),  # unchanged location
        ("requests/compat.py", "src/requests/compat.py"),  # moved under src/
        ("compat.py", None),  # two current files end in /compat.py: ambiguous
        ("gone.py", None),  # deleted since
    ],
)
def test_map_to_current(path, expected):
    current = {"README.md", "src/requests/compat.py", "tests/compat.py"}
    assert map_to_current(path, current) == expected


def test_index_maps_paths_and_parses_python_files():
    idx = build_pr_code_index(fetched(), REPO, 1565)
    by_path = {f.pr_path: f for f in idx.files}
    assert by_path["src/fixture/compat.py"].current_path == "src/fixture/compat.py"
    assert by_path["fixture/utils.py"].current_path == "lib/fixture/utils.py"
    assert by_path["fixture/old.py"].current_path is None  # removed in the PR, gone today
    assert set(idx.parsed) == {"src/fixture/compat.py", "fixture/utils.py"}
    assert idx.tree_known and idx.missing_code == []


def test_entity_ids_use_todays_path():
    idx = build_pr_code_index(fetched(), REPO, 1565)
    utils = idx.parsed["fixture/utils.py"]
    fn = utils.of_kind(EntityKind.FUNCTION)[0]
    assert fn.id == "test/fixture#fn:lib/fixture/utils.py::to_text"
    assert (
        idx.file_id(idx.find_file("fixture/utils.py")) == "test/fixture#file:lib/fixture/utils.py"
    )


@pytest.mark.parametrize(
    "written, pr_path",
    [
        ("src/fixture/compat.py", "src/fixture/compat.py"),
        ("fixture/compat.py", "src/fixture/compat.py"),  # the name before the PR renamed it
        ("./src/fixture/compat.py", "src/fixture/compat.py"),
        ("lib/fixture/utils.py", "fixture/utils.py"),  # today's path
        ("utils.py", "fixture/utils.py"),  # unique tail
        ("src\\fixture\\compat.py", "src/fixture/compat.py"),
    ],
)
def test_find_file_accepts_the_ways_a_path_gets_written(written, pr_path):
    idx = build_pr_code_index(fetched(), REPO, 1565)
    assert idx.find_file(written).pr_path == pr_path


@pytest.mark.parametrize("written", ["setup.py", "", "fixture/missing.py"])
def test_find_file_rejects_files_the_pr_did_not_change(written):
    assert build_pr_code_index(fetched(), REPO, 1565).find_file(written) is None


def test_without_a_tree_paths_stay_as_in_the_pr():
    routes = load_github_fixture("pr_1565.json")
    del routes["/repos/test/fixture/pulls/1565"]["base"]
    idx = build_pr_code_index(fetched(routes), REPO, 1565)
    assert not idx.tree_known
    assert idx.find_file("fixture/utils.py").graph_path == "fixture/utils.py"


def test_missing_blob_is_reported_not_crashed():
    store = fetched()
    del store.rows[(REPO, "blob", "c0ffee02")]
    idx = build_pr_code_index(store, REPO, 1565)
    assert idx.missing_code == ["fixture/utils.py"] and "fixture/utils.py" not in idx.parsed


def test_unknown_pr_raises_a_clear_error():
    with pytest.raises(LookupError, match="fetch it first"):
        build_pr_code_index(MemoryRawStore(), REPO, 1)
