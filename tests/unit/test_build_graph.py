from datetime import UTC, datetime

import pytest

from tests.pipeline import run_fixture
from whycode.extract.prompt import PROMPT_VERSION
from whycode.graph.build import GraphBatch, build_pr_graph
from whycode.ids import decision_id

R = "test/fixture"
PR = "test/fixture#pr:1565"
NOW = datetime(2026, 10, 28, tzinfo=UTC)


@pytest.fixture(scope="module")
def batch():
    p = run_fixture()
    return build_pr_graph(
        p.store, p.thread, p.result.decisions, p.checks,
        index=p.index, prompt_version=PROMPT_VERSION, now=NOW,
    )  # fmt: skip


def rels(batch, type_, from_label=None, to_label=None):
    return {
        pair
        for (t, fl, tl), pairs in batch.rels.items()
        if t == type_ and from_label in (None, fl) and to_label in (None, tl)
        for pair in pairs
    }


def test_every_node_has_the_repo_and_a_prefixed_id(batch):
    for label, nodes in batch.nodes.items():
        for id_, props in nodes.items():
            assert props["repo"] == R
            assert id_ == R if label == "Repo" else id_.startswith(R + "#")


def test_pr_commit_and_people(batch):
    pr = batch.nodes["PullRequest"][PR]
    assert pr["number"] == 1565 and pr["merged"] is True and pr["comment_count"] == 3
    assert isinstance(pr["merged_at"], datetime)
    commit = "test/fixture#commit:1111111111111111111111111111111111111111"
    assert (PR, commit) in rels(batch, "CONTAINS", "PullRequest", "Commit")
    assert ("test/fixture#user:alice", PR) in rels(batch, "AUTHORED", "Person", "PullRequest")
    assert ("test/fixture#user:bob", PR) in rels(batch, "REVIEWED")


def test_people_are_inactive_after_18_months(batch):
    bob = batch.nodes["Person"]["test/fixture#user:bob"]
    assert bob["last_seen"].year == 2021 and bob["active"] is False


def test_closing_and_referenced_issues(batch):
    closes = {i for _, i in rels(batch, "CLOSES")}
    refs = {i for _, i in rels(batch, "REFERENCES")}
    assert closes == {"test/fixture#issue:1500", "test/fixture#issue:1501"}
    assert refs == {"test/fixture#issue:1400", "test/fixture#issue:1502"}


def test_files_use_todays_paths_and_keep_old_ones_as_aliases(batch):
    compat = batch.nodes["File"]["test/fixture#file:src/fixture/compat.py"]
    assert compat["aliases"] == ["fixture/compat.py"]  # renamed by the PR itself
    assert compat["path"] == "src/fixture/compat.py"
    utils = batch.nodes["File"]["test/fixture#file:lib/fixture/utils.py"]
    assert utils["aliases"] == ["fixture/utils.py"] and utils["aliases_text"] == "fixture/utils.py"


def test_code_entities_and_containment(batch):
    fn = "test/fixture#fn:src/fixture/compat.py::Detector.detect"
    cls = "test/fixture#cls:src/fixture/compat.py::Detector"
    assert batch.nodes["Function"][fn]["start_line"] == 7
    assert (cls, fn) in rels(batch, "CONTAINS", "Class", "Function")
    assert ("test/fixture#file:src/fixture/compat.py", cls) in rels(
        batch, "CONTAINS", "File", "Class"
    )
    assert batch.nodes["ConfigKey"]["test/fixture#cfg:MAX_BYTES"]["value"] == "4096"


def test_modifies_files_and_exactly_the_changed_code(batch):
    commit = "test/fixture#commit:1111111111111111111111111111111111111111"
    files = {f for c, f in rels(batch, "MODIFIES", "Commit", "File") if c == commit}
    assert "test/fixture#file:README.md" in files and len(files) == 3  # old.py was removed
    code = {e for _, e in rels(batch, "MODIFIES", "Commit") if "#file:" not in e}
    assert code == {
        "test/fixture#cfg:MAX_BYTES",  # MAX_BYTES = 1024 -> 4096
        "test/fixture#fn:src/fixture/compat.py::Detector.detect",  # its return changed
        "test/fixture#fn:lib/fixture/utils.py::to_text",  # a line deleted inside it
    }
    props = batch.rels[("MODIFIES", "Commit", "Function")]
    assert props[(commit, "test/fixture#fn:src/fixture/compat.py::Detector.detect")] == {
        "added": 1,
        "removed": 1,
    }


def test_every_source_is_evidence(batch):
    ev = batch.nodes["Evidence"]
    assert "test/fixture#ev:pr:1565:ic:9001" in ev and "test/fixture#ev:issue:1500:ic:8001" in ev
    assert ev["test/fixture#ev:pr:1565:ic:9001"]["author"] == "carol"


def test_decisions_ids_links_and_spans(batch):
    d0 = decision_id(R, PR, PROMPT_VERSION, 0)
    d = batch.nodes["Decision"][d0]
    assert d["summary"] == "Switch the X parser for Y" and d["status"] == "ACTIVE"
    assert d["decided_at"] == datetime(2021, 6, 21, tzinfo=UTC)
    assert d["prompt_version"] == PROMPT_VERSION
    assert (d0, PR) in rels(batch, "DECIDED_IN")
    span = batch.rels[("SUPPORTED_BY", "Decision", "Evidence")][
        (d0, "test/fixture#ev:pr:1565:ic:9001")
    ]
    text = batch.nodes["Evidence"]["test/fixture#ev:pr:1565:ic:9001"]["text"]
    assert (
        text[span["span_start"] : span["span_end"]]
        == "We cannot ship an LGPL dependency inside an MIT library."
    )


def test_affects_only_what_the_check_kept(batch):
    d0 = decision_id(R, PR, PROMPT_VERSION, 0)
    affected = {t for d, t in rels(batch, "AFFECTS") if d == d0}
    assert affected == {
        "test/fixture#fn:src/fixture/compat.py::Detector.detect",
        "test/fixture#cfg:MAX_BYTES",
    }  # setup.py was not changed by the PR, so it is not linked


def test_proposed_and_approved_by(batch):
    d0 = decision_id(R, PR, PROMPT_VERSION, 0)
    assert (d0, "test/fixture#user:alice") in rels(batch, "PROPOSED_BY")
    assert {p for d, p in rels(batch, "APPROVED_BY") if d == d0} == {"test/fixture#user:bob"}


def test_decisions_of_the_pr_are_replaced(batch):
    assert batch.replaces_decisions_of == [("PullRequest", PR)]


def test_every_relationship_endpoint_is_a_node(batch):
    ids = {i for nodes in batch.nodes.values() for i in nodes}
    for pairs in batch.rels.values():
        for a, b in pairs:
            assert a in ids and b in ids, (a, b)


def test_labels_and_types_are_allowlisted():
    b = GraphBatch(R)
    with pytest.raises(ValueError):
        b.node("Hacker) DETACH DELETE n //", "x")
    with pytest.raises(ValueError):
        b.rel("OWNS", ("File", "a"), ("File", "b"))


def test_same_input_builds_the_same_batch():
    p = run_fixture()
    kw = dict(index=p.index, prompt_version=PROMPT_VERSION, now=NOW)
    b1 = build_pr_graph(p.store, p.thread, p.result.decisions, p.checks, **kw)
    b2 = build_pr_graph(p.store, p.thread, p.result.decisions, p.checks, **kw)
    assert b1.nodes == b2.nodes and b1.rels == b2.rels


def test_batch_accepts_every_relationship_the_schema_lists_for_commits():
    from whycode.graph.build import GraphBatch

    b = GraphBatch("psf/requests")
    a, c = ("Commit", "psf/requests#commit:a"), ("Commit", "psf/requests#commit:b")
    b.rel("REVERTS", a, c)
    assert b.count() == (0, 1)
