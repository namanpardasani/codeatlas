# CodeAtlas evaluation

Every number below was produced by a stored run (`eval_runs` table and `eval/results/*.json`, each with the git commit,
the dataset hash and the configuration). Run ids are given so a number can be traced. Nothing is estimated by hand.

**Read the caveats first.** The questions and ground truth were written by Claude, the same AI that built CodeAtlas, not
by a human who maintains these repos (see [Limitations](#limitations)). The sample is small (50 questions, 43 answerable),
so differences smaller than the confidence intervals are noise. The answer-quality judge turned out to be unusable
and its scores are not reported as results.

## What was measured

| Area | Method | Data |
|---|---|---|
| Retrieval | recall@1/3/5/10, hit@5 and MRR for 8 variants | 43 answerable questions on 4 repos |
| Answers | refusal behaviour, citation file precision/recall, verifier removals, failure categories | 50 questions (7 unanswerable) |
| Answer quality | LLM judge with a written rubric + a 15-answer spot-check | judge failed; spot-check graded by Claude (human sheet left blank) |
| Graph | precision/recall of dependency edges | 104 hand-verified edges, 41 files, 4 repos |

Repos: `psf/requests` (22 questions), `pallets/itsdangerous` (11), `sindresorhus/p-limit` (9), `chalk/chalk` (8).
7 questions are unanswerable (the repo cannot answer them), 15 are tagged `heldout`.

### Definitions

- A **target** is a ground-truth file, or a ground-truth symbol when the question lists symbols. A retrieved chunk is
  relevant to a target when it is in the right file and its **line range overlaps** the target, so fixed-size and AST
  chunks are scored identically.
- **recall@k**: fraction of a question's targets found in the top k, averaged over questions. **hit@k**: share of questions
  with at least one relevant result in the top k. **MRR**: mean of 1/rank of the first relevant result (0 if none).
  recall@k says "is it in the list", MRR says "how near the top".
- Production rules are applied in every variant: test files are excluded unless the question is about tests, and
  (after the fix below) documentation is down-weighted. The rerank variants fetch 20 candidates and keep the top 10.
- MRR confidence intervals are 95% percentile bootstrap (2000 resamples).

## Protocol (to limit overfitting)

1. Questions were written before any retrieval or answer run. One correction was made before any result existed: two chalk
   questions pointed at `vendor/` code that the analyser deliberately skips, so they were replaced.
2. Baseline runs on the full set (retrieval run 10), the **dev split** (32 questions, run 11) and the **held-out split**
   (11 questions, run 12).
3. Fixes were chosen using failures on the dev split only. The held-out split was scored once before and once after.

## Results

### Retrieval, baseline, all 43 answerable questions (run 10)

| variant | recall@1 | recall@3 | recall@5 | recall@10 | MRR | hit@5 | MRR 95% CI |
|---|---|---|---|---|---|---|---|
| fixed/vector | 0.221 | 0.512 | 0.593 | 0.779 | 0.427 | 0.628 | 0.32-0.54 |
| fixed/keyword | 0.267 | 0.465 | 0.558 | 0.663 | 0.425 | 0.628 | 0.30-0.54 |
| fixed/hybrid | 0.372 | 0.512 | 0.523 | 0.756 | 0.510 | 0.581 | 0.38-0.64 |
| ast/vector | 0.349 | 0.523 | 0.558 | 0.779 | 0.493 | 0.605 | 0.37-0.62 |
| ast/keyword | 0.116 | 0.326 | 0.453 | 0.616 | 0.280 | 0.512 | 0.19-0.38 |
| ast/hybrid | 0.267 | 0.465 | 0.616 | 0.767 | 0.451 | 0.674 | 0.34-0.56 |
| fixed/hybrid+rerank | 0.174 | 0.337 | 0.570 | 0.744 | 0.360 | 0.628 | 0.26-0.47 |
| ast/hybrid+rerank | 0.291 | 0.465 | 0.605 | 0.744 | 0.457 | 0.651 | 0.34-0.58 |

What this does and does not say:
- **AST chunks did not clearly beat fixed-size chunks.** AST has the best hit@5 for hybrid (0.674 vs 0.581) but the fixed
  baseline has the higher MRR (0.510 vs 0.451). The confidence intervals overlap heavily; with 43 questions this is a tie.
- **Hybrid beat keyword-only clearly and vector-only mostly:** AST keyword-only is the weakest variant (MRR 0.280).
- **The cross-encoder reranker did not help** (MRR 0.457 vs 0.451 for AST, and worse for fixed). The model
  (`ms-marco-MiniLM-L-6-v2`) was trained on web search, not code.

### Retrieval after the fixes, ast/hybrid (the variant the chat uses)

| split | n | | recall@1 | recall@3 | recall@5 | recall@10 | MRR | hit@5 |
|---|---|---|---|---|---|---|---|---|
| dev | 32 | before (run 11) | 0.297 | 0.500 | 0.641 | 0.797 | 0.481 | 0.688 |
| dev | 32 | after (run 24) | 0.469 | 0.703 | 0.859 | 0.922 | 0.658 | 0.906 |
| **held-out** | 11 | before (run 12) | 0.182 | 0.364 | 0.545 | 0.682 | 0.364 | 0.636 |
| **held-out** | 11 | after (run 25) | 0.364 | 0.591 | 0.591 | 0.773 | 0.542 | 0.727 |

The held-out split was not used to choose the fix and improved in the same direction (MRR +0.178 vs +0.177 on dev), but
it has only 11 questions (MRR 95% CI after: 0.31-0.77). The vector-only and keyword-only variants are unchanged by the
fix because it only acts on the hybrid fusion. Full before/after tables for all 8 variants are in runs 11/24 and 12/25.

### Graph, dependency edges (runs 9 → 23)

| repo | true edges | predicted before | precision before | predicted after | precision after | recall |
|---|---|---|---|---|---|---|
| pallets/itsdangerous | 21 | 21 | 1.000 | 21 | 1.000 | 1.000 |
| chalk/chalk | 8 | 8 | 1.000 | 8 | 1.000 | 1.000 |
| sindresorhus/p-limit | 3 | 3 | 1.000 | 3 | 1.000 | 1.000 |
| psf/requests | 72 | 78 | 0.923 | 72 | 1.000 | 1.000 |
| **micro total** | 104 | 110 | **0.945** | 104 | **1.000** | 1.000 |

Recall was 1.000 both times. Perfect scores on 41 files are a **weak claim**: these are mostly plain relative imports.
The only error found (6 spurious edges, all in requests) is described under fixes.

### Answers (runs 19 → 26), local Qwen2.5-Coder-1.5B

| metric | before (run 19) | after (run 26) |
|---|---|---|
| answerable questions refused (false refusal) | 0.093 (4 of 43) | 0.186 (8 of 43) |
| unanswerable questions refused (correct refusal) | 0.714 (5 of 7) | 0.714 (5 of 7) |
| citation file precision (model-written citations vs ground-truth files) | 0.800 | 0.759 |
| citation file recall | 0.103 | 0.229 |
| answers where the verifier removed ≥1 sentence | 0.415 | 0.514 |
| judge-independent failure categories | over-refusal 4, hallucination 2 | over-refusal 8, hallucination 2 |

**The answer-level changes are mixed and mostly within noise** (7 and 43 questions, a stochastic model at temperature 0.1):
- The targeted fix worked on its case: before, the AES question about itsdangerous (which only signs, never encrypts) got an
  invented "AES-128 in CBC mode" answer; after, it is refused. But the HTTP/2 question for requests went from refused to
  answered (a different hallucination), so the correct-refusal rate did not change.
- False refusals doubled. Most of the new refusals are answers the stricter verifier discarded because every sentence was
  removed (for example, sentences naming `chalk.red.bold` from the question itself were removed as "not in the retrieved
  code"). That is a real cost of the stricter verifier, not proven to be an improvement in answer quality.
- Citation recall improved (0.10 → 0.23) because retrieval now surfaces source files instead of docs, but most answers
  still cite only one file.

### Answer quality: the judge failed, and what was done instead

A rubric (`eval/RUBRIC.md`: correctness, groundedness, citation validity, 0-2) was applied by an LLM judge. The only judge
available at zero cost was the same 1.5B local model that wrote the answers:

- Version 1 of the prompt (run 22) gave 0 on all three dimensions for 38 of 41 answers and flagged unsupported claims in
  40 of 41 (reported "hallucination rate" 1.000). It was mostly echoing the zeros in my JSON template.
- After fixing the template (rubric-v2) a 5-answer check returned 2/2/2 for every answer, including one whose reason text
  described the wrong function. The judge is not discriminating in either direction.
- Agreement with Claude's grades on the 15-answer sample (`eval/spotcheck_claude.csv`), for the version-1 judge:
  Cohen's kappa 0.06 (correctness), 0.07 (groundedness), 0.20 (citation validity). That is close to chance.

**Therefore no judge-based numbers are published.** The 15-answer sample (seed 20261020, answers the model actually wrote) was
graded by Claude using the same rubric: mean correctness 1.00, groundedness 1.07, citation validity 0.67 on a 0-2 scale; 4 of
15 answers scored 0 for both correctness and groundedness. These grades have three limits: Claude also wrote the questions
and the notes, a single grader on 15 items has no error bar, and Claude saw the ground truth. **`eval/spotcheck.csv` is the
same sample left blank for a human to grade**; when it is filled, `python -m analyzer.evalkit agreement` reports
judge-vs-human agreement.

### Failure analysis (ast/hybrid, categories assigned by rules in `evalkit/failures.py`)

| run | retrieval miss | wrong chunking | import-resolution error |
|---|---|---|---|
| dev baseline (11) | 3 | 2 | - |
| dev after (24) | 1 | 1 | - |
| held-out baseline (12) | 2 | 1 | - |
| held-out after (25) | 1 | 1 | - |
| graph baseline (9) | - | - | 6 spurious edges |
| graph after (23) | - | - | 0 |

("Wrong chunking" means the right file was retrieved but no chunk overlapped the right symbol. The remaining cases are
`limitFunction`/`validateConcurrency` sitting in a merged "group" chunk and a `CaseInsensitiveDict` question phrased in
terms of headers rather than the class.)

## What was changed because of the results

1. **Ranking: source before documentation (retrieval miss).** In the baseline, README, `.rst` and `.d.ts` chunks occupied the
   top ranks for "how does it work" questions because they use the same words as the question. In hybrid mode, chunks from
   documentation, type declarations, changelogs, examples and benchmarks now have their fused score multiplied by 0.7
   unless the question asks for docs, install steps, usage, examples or types. 0.85 / 0.7 / 0.5 gave dev MRR 0.622 / 0.631 /
   0.631 (a plateau; measured before the examples/benchmarks patterns were added, which lifted it to 0.658); 0.7 was chosen. Cost: usage-style questions that don't say so ("how do I discard queued tasks?") now
   prefer implementation over the README. This is a policy choice for a tool about *how the code works*.
2. **Verifier: fabricated code and acronyms (hallucination).** The verifier flagged but kept a fenced code block that was
   not in the retrieved code (requests answer invented a whole `asyncio` example), and never checked acronyms ("AES-128",
   "CBC"). It now removes code blocks whose lines are mostly absent from the evidence and sentences naming acronyms or
   constants absent from it. Tests were rewritten for the new behaviour.
3. **Import resolution (import-resolution error).** `from . import _types` produced an edge to `__init__.py` as well as to
   `_types.py`, which fabricates a cycle through the package that re-exports its children. A package `__init__` is now only a
   dependency when some imported name is not a submodule. Precision 0.923 → 1.000 on requests. Existing test
   `test_relative_levels` encoded the old behaviour and was updated deliberately; `PIPELINE_VERSION` is now 8.

## Limitations

- **Authorship and circularity.** Claude wrote the questions, notes, files and symbols after reading the source, and also
  built the system being tested. Question style may unconsciously match how CodeAtlas retrieves. The ground truth was
  checked against the source, not by an independent human. A human-written set would be a stronger test.
- **Size.** 43 answerable questions; MRR intervals are about ±0.13 on the full set and wider per split (held-out n=11).
  Most before/after differences on the held-out split are not statistically separable.
- **Tuning on the dev split.** The 0.7 weight and the examples/benchmarks patterns were selected on dev (the plateau test
  shows the weight is not sensitive). The same questions were also used to *find* the failure causes.
- **Ground truth granularity.** Many questions have one correct file. An answer that finds an equally good second place
  (for example a test that demonstrates the behaviour) scores as a miss.
- **Answer evaluation is weak.** The generator is a 1.5B local model, the judge failed, and the only quality grades come from
  one 15-answer sample graded by the question author. Refusal rates rest on 7 unanswerable questions.
- **Graph evaluation is easy.** Only static imports among listed files, no aliases, dynamic imports or monorepo paths.
  Perfect scores say the resolver handles these simple layouts, not that it is correct in general.
- **Stochasticity.** Retrieval is deterministic; generation is not. Answer metrics were run once per condition.
- **Not tested:** other languages, large repos, queries unlike these. Rerank was tested with one general-purpose model only.

## Reproduce

```bash
cd workers/analyzer
uv run python -m analyzer.evalkit validate
uv run python -m analyzer.evalkit --exclude-tag heldout retrieval --label dev --embed-missing
uv run python -m analyzer.evalkit --only-tag heldout retrieval --label heldout     # score once
LLM_PROVIDER=llamacpp LLM_MODEL=qwen2.5-coder-1.5b uv run python -m analyzer.evalkit answers --label run
uv run python -m analyzer.evalkit graph-eval --label run
uv run python -m analyzer.evalkit report --retrieval <id> --compare <baseline id>
```

Tests: `tests/test_eval_metrics.py` (metric definitions against hand-computed values) and `tests/test_eval_harness.py`.
Charts were not produced; the tables above carry the data.
