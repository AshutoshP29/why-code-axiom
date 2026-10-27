import pytest

from whycode.extract.quotes import find_quote, normalize

SRC = "We cannot ship an LGPL dependency\r\ninside an  MIT library.\n\nAgreed, let's switch."


def test_exact_quote_passes_with_original_offsets():
    span = find_quote("let's switch.", SRC)
    assert SRC[span.start : span.end] == "let's switch."


def test_quote_across_crlf_and_double_space_passes():
    span = find_quote("LGPL dependency inside an MIT library.", SRC)
    assert span is not None
    assert SRC[span.start : span.end] == "LGPL dependency\r\ninside an  MIT library."


@pytest.mark.parametrize(
    "variant",
    [
        "LGPL dependency\ninside an MIT library.",
        "LGPL   dependency \t inside an MIT library.",
        "  LGPL dependency inside an MIT library.  ",
        "LGPL dependency inside an MIT library.",  # non-breaking space
    ],
)
def test_whitespace_differences_are_forgiven(variant):
    assert find_quote(variant, SRC) is not None


@pytest.mark.parametrize(
    "altered",
    [
        "We can not ship an LGPL dependency",  # words changed
        "we cannot ship an LGPL dependency",  # case changed
        "Agreed, let’s switch.",  # curly apostrophe instead of straight
        "Agreed, let's switch!",  # punctuation changed
        "We cannot ship ... MIT library.",  # ellipsis
        "inside an MIT library. Agreed let's",  # comma dropped
        "LGPLdependency inside",  # whitespace removed is not whitespace collapsed
    ],
)
def test_altered_quotes_are_rejected(altered):
    assert find_quote(altered, SRC) is None


@pytest.mark.parametrize("empty", ["", "   ", "\n\t"])
def test_empty_quote_is_rejected(empty):
    assert find_quote(empty, SRC) is None


def test_normalize_rules():
    assert normalize(" a\r\n\tb  c d \n") == "a b c d"
