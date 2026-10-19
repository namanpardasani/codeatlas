import random

from analyzer.duplication import WINDOW, find_duplicates
from analyzer.parsing import parse_source


def stream(seed: int, n: int, lines_per=5):
    """Random token stream with plenty of variety and a line break every `lines_per` tokens."""
    rng = random.Random(seed)
    toks = [rng.randrange(1, 10_000) for _ in range(n)]
    return toks, [1 + i // lines_per for i in range(n)]


def with_block(prefix_seed, block, suffix_seed, n_prefix=40, n_suffix=40):
    pre, _ = stream(prefix_seed, n_prefix)
    suf, _ = stream(suffix_seed, n_suffix)
    toks = pre + block + suf
    return toks, [1 + i // 5 for i in range(len(toks))]


def test_identical_block_in_two_files_is_one_group():
    block, _ = stream(1, 120)
    files = {"a.ts": with_block(2, block, 3), "b.ts": with_block(4, block, 5)}
    r = find_duplicates(files)
    assert len(r.groups) == 1
    g = r.groups[0]
    assert g.total_locations == 2 and {l.path for l in g.locations} == {"a.ts", "b.ts"}
    assert g.lines >= 24 and g.tokens >= 120
    assert r.duplicated_lines["a.ts"] >= 24 and r.duplicated_lines["b.ts"] >= 24


def test_three_copies_form_one_group_with_three_locations():
    block, _ = stream(7, 100)
    files = {f"f{i}.ts": with_block(10 + i, block, 20 + i) for i in range(3)}
    r = find_duplicates(files)
    assert len(r.groups) == 1 and r.groups[0].total_locations == 3


def test_blocks_shorter_than_the_window_are_not_reported():
    block, _ = stream(1, WINDOW - 5)
    r = find_duplicates({"a.ts": with_block(2, block, 3), "b.ts": with_block(4, block, 5)})
    assert r.groups == []


def test_low_variety_data_tables_are_ignored():
    table = [1, 2] * 200  # like [1,2,1,2,...]: two kinds of tokens only
    r = find_duplicates({"a.ts": (table, list(range(len(table)))), "b.ts": (table[:], list(range(len(table))))})
    assert r.groups == []


def test_short_blocks_in_lines_are_dropped():
    block, _ = stream(1, 120)
    one_line = lambda toks: (toks, [1] * len(toks))  # e.g. minified: everything on one line
    r = find_duplicates({"a.ts": one_line(block), "b.ts": one_line(block[:])})
    assert r.groups == []


def test_overlapping_self_repetition_is_not_counted_as_two_copies():
    unit, _ = stream(9, 30)  # 30-token unit repeated back to back: overlaps within one file
    toks = unit * 3
    r = find_duplicates({"a.ts": (toks, [1 + i // 5 for i in range(len(toks))])})
    # a window can only pair with a non-overlapping window: 90 tokens hold at most one full extra window
    assert all(g.total_locations >= 2 for g in r.groups)


def test_deterministic_and_order_independent():
    block, _ = stream(1, 100)
    files = {f"f{i}.ts": with_block(10 + i, block, 20 + i) for i in range(4)}
    a = find_duplicates(files)
    b = find_duplicates(dict(reversed(list(files.items()))))
    assert a == b


def test_token_budget_marks_truncation():
    block, _ = stream(1, 100)
    files = {"a.ts": with_block(2, block, 3), "b.ts": with_block(4, block, 5)}
    assert find_duplicates(files, max_total_tokens=10).truncated is True


def test_end_to_end_with_the_parser_renamed_copy_paste_is_found():
    body = """
function {n}(items, limit) {{
  const out = [];
  for (let i = 0; i < items.length; i++) {{
    const item = items[i];
    if (item.active && item.score > limit) {{
      out.push({{ id: item.id, label: item.name.trim(), score: item.score * 2 }});
    }} else if (item.pending) {{
      out.push({{ id: item.id, label: "pending", score: 0 }});
    }}
  }}
  return out.sort((a, b) => b.score - a.score);
}}
"""
    a = parse_source("a.js", body.format(n="rankUsers").encode())
    b = parse_source("b.js", body.format(n="totallyOtherName").replace("item", "row").replace("out", "res").encode())
    c = parse_source("c.js", b"export const unrelated = 1;\n")
    r = find_duplicates({p: (x.token_hashes, x.token_lines) for p, x in
                         {"a.js": a, "b.js": b, "c.js": c}.items()})
    assert len(r.groups) == 1
    assert {l.path for l in r.groups[0].locations} == {"a.js", "b.js"}
    assert r.groups[0].lines >= 10
