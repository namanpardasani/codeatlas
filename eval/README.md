# Evaluation inputs and how to run them

The harness is in `workers/analyzer/analyzer/evalkit/`. It evaluates only what you write here: it never makes up
questions, and an incomplete file stops the run with a list of what is missing.

## 1. `eval/questions.yaml` (you write this)

About 50 questions over 3-5 repos that are already analysed in CodeAtlas (submit them in the app first; the repo
name is `owner/name`). Write them yourself from your own knowledge of those repos.

```yaml
version: 1
questions:
  - id: req-001                        # unique, stable
    repo: psf/requests                 # owner/name, as shown in the app
    question: "Where are redirects followed and how is the redirect limit enforced?"
    answer_notes: >                    # ground truth, in your words: the facts a correct answer must contain
      Session.resolve_redirects loops over the redirect chain; it raises TooManyRedirects when
      max_redirects is exceeded; each hop is sent through Session.send with allow_redirects=False.
    files: [src/requests/sessions.py]  # the correct file(s); a retrieval hit must land in one of them
    symbols: [SessionRedirectMixin.resolve_redirects]   # optional: narrows "correct" to these symbols' lines
    answerable: true                   # optional (default true). false = the repo does NOT contain the answer
    tags: [control-flow]               # optional, for slicing results
```

Rules the validator enforces:
- `id`, `repo`, `question`, `answer_notes` are required; ids are unique.
- An answerable question needs at least one path in `files` (exact path in the analysed repo).
- An unanswerable question (`answerable: false`) has NO `files`; `answer_notes` says why the repo cannot answer it.
  Include some (about 5-8): without them refusal quality and hallucination on missing information cannot be measured.
- `symbols` use the parser's names: `name` or `Class.method`, and must exist in the listed files.

Good practice (it keeps the numbers honest):
- Write the questions BEFORE looking at what the system retrieves; do not tune them to pass.
- Mix kinds: "where is X defined", "how does X work", "what calls/depends on X", cross-file questions with 2+
  files, a few with vague wording, a few that need a test file.
- Keep a split in mind: mark about 15 questions with `tags: [heldout]`. Fixes are developed on the rest; the
  held-out ones are scored once at the end so the final number is not tuned to them.

## 2. `eval/graph_truth.yaml` (you write this, small repos only)

A CLOSED set of files you verified by reading, and every true import edge between them (direction: importer first).

```yaml
version: 1
repos:
  - repo: sindresorhus/p-limit
    files: [index.js, test.js, index.d.ts]
    edges:
      - [test.js, index.js]
```

## 3. Commands (from `workers/analyzer`)

```bash
uv run python -m analyzer.evalkit validate                 # what is missing / wrong
uv run python -m analyzer.evalkit retrieval --label baseline --embed-missing   # 8 variants (fixed/ast x vector/keyword/hybrid, +rerank)
uv run python -m analyzer.evalkit answers --label baseline # real chat pipeline, needs LLM_PROVIDER (local llama.cpp is free)
uv run python -m analyzer.evalkit judge --estimate         # tokens and whether it costs money, BEFORE any call
uv run python -m analyzer.evalkit judge --answers <run id>
uv run python -m analyzer.evalkit spotcheck --answers <run id>   # eval/spotcheck.csv + RUBRIC.md: you grade 15 answers
uv run python -m analyzer.evalkit agreement                # judge vs your grades
uv run python -m analyzer.evalkit graph-eval --label baseline
uv run python -m analyzer.evalkit failures --retrieval <id> --answers <id> --judge <id> --graph-run <id>
uv run python -m analyzer.evalkit report --retrieval <id> --compare <baseline id>
```

Every run is stored in the `eval_runs` table and as JSON in `eval/results/`, with the git commit, the dataset hash
and the configuration, so a published number can be traced to the run that produced it.

## Judge model and cost

By default the judge is whatever `LLM_PROVIDER` points at (local llama.cpp + Qwen2.5-Coder-1.5B: free, but a weak
judge that also grades its own answers). Set `EVAL_JUDGE_PROVIDER`, `EVAL_JUDGE_MODEL`, `EVAL_JUDGE_API_KEY` to use
a different, stronger model. Paid judges refuse to run without `--yes` after the estimate has been shown.
