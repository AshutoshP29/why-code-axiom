"""Exact-quote check: an evidence quote must be a verbatim substring of its stored source text.

Whitespace rule (the only normalisation, applied identically to quote and source):
  - CRLF and CR become LF,
  - non-breaking and other Unicode spaces count as whitespace,
  - every run of whitespace (spaces, tabs, newlines) becomes one space,
  - leading and trailing whitespace is ignored.
Nothing else is forgiven: case, punctuation, quote styles, Markdown and ellipses must match.
"""

import re
from dataclasses import dataclass

_WS = re.compile(r"\s+")  # str patterns are Unicode-aware: includes  ,  , etc.


def normalize(text: str) -> str:
    return _WS.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalised text plus, for each of its characters, the index in the original text."""
    out: list[str] = []
    index: list[int] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if out:  # drop leading whitespace
                out.append(" ")
                index.append(i)
            i = j
        else:
            out.append(text[i])
            index.append(i)
            i += 1
    if out and out[-1] == " ":
        out.pop()
        index.pop()
    return "".join(out), index


@dataclass(frozen=True)
class Span:
    start: int  # offsets into the ORIGINAL source text
    end: int


def find_quote(quote: str, source_text: str) -> Span | None:
    """Where the quote occurs in source_text under the whitespace rule, or None."""
    q = normalize(quote)
    if not q:
        return None
    norm, index = _normalize_with_map(source_text)
    pos = norm.find(q)
    if pos < 0:
        return None
    return Span(index[pos], index[pos + len(q) - 1] + 1)
