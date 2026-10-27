import pytest

from whycode.ingest.links import (
    Ref,
    closing_refs,
    parse_refs,
    parse_revert,
    subject_pr_numbers,
)

R = "psf/requests"


def nums(text, repo=R):
    return [(r.repo, r.number, r.closing) for r in parse_refs(text, repo)]


# --- plain references ---------------------------------------------------------------


def test_plain_hash_ref():
    assert nums("see #123 for context") == [(R, 123, False)]


def test_multiple_refs_in_order_and_deduplicated():
    assert nums("#5, then #3 and #5 again") == [(R, 5, False), (R, 3, False)]


def test_cross_repo_ref_is_normalized():
    assert nums("as in Pallets/Flask#1565") == [("pallets/flask", 1565, False)]


def test_gh_style_ref():
    assert nums("tracked in GH-42") == [(R, 42, False)]


def test_github_url_is_a_ref():
    text = "https://github.com/psf/requests/issues/812#issuecomment-1 and https://github.com/psf/requests/pull/9"
    assert nums(text) == [(R, 812, False), (R, 9, False)]


@pytest.mark.parametrize(
    "text",
    [
        "a number alone 123",
        "https://example.com/page#12",
        "https://example.com/#12",
        "it&#39;s fine",
        "issue#12 glued to a word",
        "##12 double hash",
        "#12abc not a number",
        "version 2.#1 dotted",
    ],
)
def test_not_refs(text):
    assert parse_refs(text, R) == []


def test_ref_in_parentheses_and_punctuation():
    assert nums("(#6767), #1.") == [(R, 6767, False), (R, 1, False)]


# --- closing references ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "fixes #12",
        "Fixes #12",
        "fixed #12",
        "fix #12",
        "closes #12",
        "close #12",
        "closed #12",
        "resolves #12",
        "Resolve #12",
        "resolved: #12",
        "Fixes https://github.com/psf/requests/issues/12",
    ],
)
def test_closing_keywords(text):
    assert closing_refs(text, R) == [Ref(R, 12, True)]


def test_only_the_ref_right_after_the_keyword_closes():
    # GitHub closes #1 only; "#2" is a plain mention.
    assert nums("Fixes #1 and #2") == [(R, 1, True), (R, 2, False)]


def test_each_keyword_closes_its_own_ref():
    assert nums("fixes #1, closes psf/requests#2") == [(R, 1, True), (R, 2, True)]


def test_keyword_inside_word_does_not_close():
    assert nums("prefixes #3 and unresolved #4") == [(R, 3, False), (R, 4, False)]


def test_closing_wins_over_earlier_plain_mention():
    assert nums("see #7. Fixes #7") == [(R, 7, True)]


# --- commit subjects ------------------------------------------------------------------


def test_squash_subject_pr_number():
    assert subject_pr_numbers("Switch to charset_normalizer (#5797)\n\nbody (#1)") == [5797]


def test_subject_multiple_and_cross_repo():
    assert subject_pr_numbers("Fix a (#1) (psf/requests#2)") == [1, 2]


def test_subject_without_pr():
    assert subject_pr_numbers("Fix #12 without parentheses") == []
    assert subject_pr_numbers("") == []


# --- reverts --------------------------------------------------------------------------


def test_git_revert_message():
    msg = 'Revert "Use Y instead of X"\n\nThis reverts commit ABC1234def5678.'
    r = parse_revert(msg, R)
    assert r.subject == "Use Y instead of X"
    assert r.shas == ("abc1234def5678",)


def test_revert_of_a_revert_keeps_inner_subject():
    assert parse_revert('Revert "Revert "x""', R).subject == 'Revert "x"'


def test_reverts_pr_reference():
    r = parse_revert("Back out the change; reverts #5797", R)
    assert r.subject is None and r.refs == (Ref(R, 5797),)


@pytest.mark.parametrize(
    "msg",
    ["Fix revert handling in adapters", "Revert to the old default", "Reverting is hard (#12)"],
)
def test_not_reverts(msg):
    assert parse_revert(msg, R) is None
