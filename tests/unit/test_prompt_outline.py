from tests.fakes import FakeProvider, MemoryLLMCache
from tests.unit.test_code_index import REPO, fetched
from whycode.code.index import build_pr_code_index
from whycode.extract import prompt as prompt_module
from whycode.extract.extractor import chunk_sources, extract_thread
from whycode.extract.prompt import PROMPT_VERSION, SYSTEM, build_user_prompt, render_code_outline
from whycode.extract.sources import load_thread
from whycode.llm.client import Budget, LLMClient


def setup():
    store = fetched()
    return load_thread(store, REPO, 1565), build_pr_code_index(store, REPO, 1565)


def test_outline_lists_real_names_per_file_by_pr_path():
    _, index = setup()
    outline = render_code_outline(index)
    assert outline.splitlines() == [
        "- src/fixture/compat.py",
        "  classes: Detector",
        "  functions: Detector.detect, detect",
        "  config: DEFAULT_ENCODING, MAX_BYTES, Detector.detect.limit",  # limit=MAX_BYTES
        "- fixture/utils.py",
        "  functions: to_text",
        "  config: to_text.encoding",
    ]  # README.md (not Python) and fixture/old.py (removed) are not listed


def test_outline_caps_very_long_lists(monkeypatch):
    _, index = setup()
    monkeypatch.setattr(prompt_module, "MAX_NAMES_PER_KIND", 1)
    assert "  functions: Detector.detect, ... (1 more)" in render_code_outline(index)


def test_prompt_places_the_outline_before_the_sources():
    thread, index = setup()
    user = build_user_prompt(thread, thread.sources, 1, 1, render_code_outline(index))
    assert (
        user.index("CHANGED FILES:") < user.index("CODE IN CHANGED FILES") < user.index("SOURCES")
    )


def test_prompt_without_outline_has_no_code_section():
    thread, _ = setup()
    assert "CODE IN CHANGED FILES" not in build_user_prompt(thread, thread.sources, 1, 1)


def test_rules_ask_for_specific_listed_names():
    assert PROMPT_VERSION == "extract-v2"
    assert "written\n     exactly as listed there" in SYSTEM
    assert "never invent a name that is not\n   listed" in SYSTEM
    assert '{"kind": "class"' in SYSTEM


def test_every_chunk_carries_the_outline_even_split_ones():
    thread, index = setup()
    outline = render_code_outline(index)
    n = len(chunk_sources(thread, 150))
    gem = FakeProvider("gemini", "gem")
    extract_thread(
        thread,
        LLMClient([gem], MemoryLLMCache(), Budget(50)),
        max_chars=150,
        code_outline=outline,
    )
    assert len(gem.calls) == n
    assert all(outline in user for _, user in gem.calls)
