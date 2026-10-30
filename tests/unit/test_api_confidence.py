import pytest

from whycode.api.confidence import THRESHOLDS, WEIGHTS, Signals, factors, score, verdict, warning


def by_label(fs):
    return {f.label: f for f in fs}


def test_weights_sum_to_one_and_thresholds_are_the_contract_ones():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert (THRESHOLDS.answer, THRESHOLDS.refuse) == (0.70, 0.40)


def test_explicit_decision_with_two_sources_scores_full():
    fs = factors(Signals(1.0, "EXPLICIT", 2, "none", True))
    assert score(fs) == 1.0
    assert verdict(score(fs)) == "answered"
    assert [f.label for f in fs] == list(WEIGHTS)


def test_explicit_beats_inferred():
    explicit = score(factors(Signals(1.0, "EXPLICIT", 1, "none", True)))
    inferred = score(factors(Signals(1.0, "INFERRED", 1, "none", True)))
    assert explicit > inferred
    assert (explicit, inferred) == (0.9, 0.78)


def test_weak_search_match_on_an_inferred_decision_is_hedged():
    fs = factors(Signals(0.3, "INFERRED", 1, "none", True))
    assert score(fs) == 0.6
    assert verdict(score(fs)) == "hedged"


def test_no_decision_is_always_refused_even_with_a_perfect_match():
    fs = factors(Signals(1.0, None))
    assert score(fs) == 0.25
    assert verdict(score(fs)) == "refused"
    f = by_label(fs)
    assert f["Supersession resolved"].tone == f["Citation pass"].tone == "neutral"


def test_no_match_scores_zero():
    fs = factors(Signals(None, None))
    assert score(fs) == 0.0
    assert by_label(fs)["Entity match"].display == "No match"


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [(0.70, "answered"), (0.69, "hedged"), (0.40, "hedged"), (0.39, "refused"), (1.0, "answered")],
)
def test_verdict_boundaries(confidence, expected):
    assert verdict(confidence) == expected


@pytest.mark.parametrize(
    ("supersession", "value", "display"),
    [
        ("none", 1, "Not applicable"),
        ("resolved", 1, "Yes"),
        ("pending", 0.5, "Refined, not settled"),
    ],
)
def test_supersession_factor(supersession, value, display):
    f = by_label(factors(Signals(1.0, "EXPLICIT", 2, supersession, True)))["Supersession resolved"]
    assert (f.value, f.display) == (value, display)


def test_unverified_citations_cost_their_weight():
    fs = factors(Signals(1.0, "EXPLICIT", 2, "none", False))
    assert score(fs) == 0.85
    assert by_label(fs)["Citation pass"].tone == "bad"


def test_sources_display_and_clamped_match():
    f = by_label(factors(Signals(1.7, "EXPLICIT", 3, "none", True)))
    assert f["Independent sources"].display == "3 sources"
    assert f["Entity match"].value == 1.0
    assert by_label(factors(Signals(1.0, "EXPLICIT", 1)))["Independent sources"].display == (
        "1 of 2 needed"
    )


def test_warning_names_only_the_weak_factors():
    text = warning(factors(Signals(0.3, "INFERRED", 1, "none", True)))
    assert "entity match (30%)" in text
    assert "evidence directness (Inferred)" in text
    assert "independent sources (1 of 2 needed)" in text
    assert "citation" not in text


def test_warning_without_weak_factors_still_says_something():
    assert "threshold" in warning(factors(Signals(1.0, "EXPLICIT", 2, "none", True)))
