"""Citation verification: every way a model's citations can be wrong."""
import pytest

from analyzer.rag.context import ContextChunk
from analyzer.rag.verify import is_not_found, verify_answer
from analyzer.search import Hit


def chunk(label, path, start, end, content, symbol=None, chunk_id=None):
    h = Hit(chunk_id or int(label[1:]), path, "python", "function", symbol, None, start, end, "", content, 0.5)
    return ContextChunk(label, h, start, end, "")


CHUNKS = [
    chunk("C1", "src/retry.py", 4, 14, "def retry_with_backoff(fn, attempts=5):\n    time.sleep(delay)\n    delay *= 2\n", "retry_with_backoff"),
    chunk("C2", "src/auth.py", 3, 6, "def verify_password(plain, hashed):\n    return hashlib.sha256(plain)\n", "verify_password"),
]


def v(text, chunks=CHUNKS):
    return verify_answer(text, chunks)


def test_valid_chunk_and_line_citations_pass_untouched():
    r = v("`retry_with_backoff` sleeps between attempts [C1:5-6]. Passwords are hashed with sha256 [C2].")
    assert r.status == "answered" and r.removed == [] and r.issues == []
    assert [(c.label, c.path, c.start_line, c.end_line) for c in r.citations] == [("C1", "src/retry.py", 5, 6), ("C2", "src/auth.py", 3, 6)]
    assert "[C1:5-6]" in r.text and "[C2]" in r.text


def test_citation_of_a_chunk_that_was_never_retrieved_is_rejected_and_the_claim_removed():
    r = v("`retry_with_backoff` sleeps between attempts [C1]. The cache layer is implemented elsewhere [C9].")
    assert r.status == "partial" and "cache layer" not in r.text and "sleeps between attempts" in r.text
    assert any("C9" in i for i in r.issues) and len(r.removed) == 1


@pytest.mark.parametrize("cite", ["[C1:1-2]", "[C1:13-40]", "[C1:900]", "[C1:9-5]"])
def test_line_ranges_outside_the_shown_chunk_are_not_real_lines(cite):
    r = v(f"It doubles the delay each time {cite}. Passwords are checked with sha256 [C2].")
    assert "doubles" not in r.text and r.status == "partial" and [c.label for c in r.citations] == ["C2"]


def test_multi_citations_in_one_bracket_are_validated_individually():
    r = v("Retrying and password checks are separate concerns in this repo [C1, C2:3-4, C7].")
    assert [c.label for c in r.citations] == ["C1", "C2"]
    assert "[C1, C2:3-4]" in r.text and "C7" not in r.text and r.status == "answered"


def test_a_hallucinated_symbol_is_removed_even_when_the_citation_is_real():
    r = v("`retry_with_backoff` retries on failure [C1]. It also calls `exponential_jitter_policy` to randomise delays [C1].")
    assert "exponential_jitter_policy" not in r.text and r.removed and "retries on failure" in r.text


def test_symbols_found_anywhere_in_the_retrieved_code_or_paths_are_fine():
    r = v("`retry_with_backoff()` is in `src/retry.py` and uses `time.sleep` [C1]. `verify_password` lives next to it [C2].")
    assert r.status == "answered" and r.removed == []


def test_builtins_and_expressions_in_backticks_are_not_treated_as_symbols():
    r = v("It returns `None` when `attempts == 0` and the delay is `base * 2` [C1].")
    assert r.status == "answered"


def test_uncited_claims_are_kept_but_flagged_not_silently_trusted():
    r = v("`retry_with_backoff` sleeps between attempts [C1]. The function raises `ValueError` on bad input.")
    assert r.status == "partial" and "uncited_claim" in r.issues
    assert any(c.status == "uncited" for c in r.claims) and "raises" in r.text


def test_no_valid_citation_anywhere_discards_the_whole_answer():
    r = v("The system uses a fancy cache. It retries three times [C9].")
    assert r.status == "not_found" and "couldn't find" in r.text and r.citations == []
    assert r.discarded and "fancy cache" in r.discarded and "no_valid_citation" in r.issues


def test_not_found_answers_pass_through_and_are_recognised():
    for t in ["I couldn't find this in the repo.", "I couldn’t find this in the repo. The excerpts only cover auth.", "I could not find it."]:
        assert is_not_found(t) and v(t).status == "not_found"
    assert not is_not_found("The function finds nothing in the repo.")


def test_citation_after_the_full_stop_belongs_to_the_sentence_before():
    r = v("`retry_with_backoff` doubles the delay. [C1] It is defined in `src/retry.py`. [C1]")
    assert r.status == "answered" and r.text.count("[C1]") == 2 and r.removed == []


def test_bullets_headings_and_paragraphs_keep_their_structure():
    text = "## How it works\n\n- `retry_with_backoff` sleeps between attempts [C1].\n- A made up thing exists [C8].\n- Hashing uses sha256 [C2].\n"
    r = v(text)
    assert r.text.splitlines()[0] == "## How it works"
    assert "- `retry_with_backoff` sleeps between attempts [C1]." in r.text and "made up" not in r.text
    assert "- Hashing uses sha256 [C2]." in r.text


def test_code_blocks_are_kept_and_flagged_when_they_are_not_from_the_repo():
    quoted = "Here is the code [C1]:\n```python\ndef retry_with_backoff(fn, attempts=5):\n    time.sleep(delay)\n```"
    assert v(quoted).status == "answered"
    invented = "It works like this [C1]:\n```python\nfor attempt in range(10):\n    requests.get(url, retries=attempt)\n```"
    r = v(invented)
    assert r.status == "partial" and "code_not_in_repo" in r.issues and "requests.get" in r.text


def test_verification_is_idempotent():
    first = v("`retry_with_backoff` sleeps [C1:5-6]. Made up [C9]. The function raises `ValueError` always.")
    second = verify_answer(first.text, CHUNKS)
    assert second.text == first.text and [c.label for c in second.citations] == [c.label for c in first.citations]


@pytest.mark.parametrize("text", ["", "   ", "[]", "[C1", "C1]", "```", "```\nunterminated", "[C1:]", "[C:1-2]", "[C1:a-b]",
                                  "\u0000\u0001", "x" * 20000, "[C1]" * 500, "- \n- \n#", "`" * 99])
def test_garbage_never_crashes_the_verifier(text):
    r = v(text)
    assert r.status in ("answered", "partial", "not_found")


def test_huge_answers_stay_fast():
    import time
    t = time.time()
    v(("`retry_with_backoff` sleeps between attempts [C1]. " * 3000))
    assert time.time() - t < 3
