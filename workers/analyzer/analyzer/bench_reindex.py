"""Measure full vs incremental re-analysis on a real repository.

    uv run python -m analyzer.bench_reindex --url https://github.com/psf/requests --edits 5 [--hash-embedder]

Method (everything runs the real pipeline against the dev database, with a throwaway repo row that is deleted at the end):
  1. clone the repo once into a temp dir
  2. full analysis                      (first run; the embedding cache may or may not be warm)
  3. full analysis, COLD vector cache   (this repo's chunk vectors removed from the cache first: worst case)
  4. full analysis, WARM vector cache   (best case for a full run: every vector is cached)
  5. incremental analysis, no changes   (the fixed overhead of the diff)
  6. edit N source files (append a small function to each), incremental analysis
  7. full analysis of the SAME edited tree (warm), for an apples-to-apples comparison
The embedding model dominates a cold run, so the report separates stage timings.
"""
import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from . import db
from .analysis import analyze_checkout
from .clone import clone
from .embeddings import HashEmbedder, get_embedder
from .parsing import supported

SKIP = ("test", "tests", "docs", "examples", "benchmarks")


def pick_files(root: Path, n: int) -> list[Path]:
    cands = sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and p.suffix in (".py", ".ts", ".js", ".tsx", ".jsx")
                   and supported(str(p)) and not any(part in SKIP for part in p.relative_to(root).parts))
    if not cands:
        return []
    step = max(1, len(cands) // n)
    return cands[::step][:n]


def edit(path: Path, k: int) -> None:
    text = path.read_text(errors="replace")
    add = (f"\n\ndef _bench_edit_{k}():\n    return {k}\n" if path.suffix == ".py"
           else f"\nexport const benchEdit{k} = {k};\n")
    path.write_text(text + add)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", required=True)
    ap.add_argument("--edits", type=int, default=5)
    ap.add_argument("--hash-embedder", action="store_true", help="skip the real model (measures parsing/DB work only)")
    ap.add_argument("--out", help="write the results as JSON")
    args = ap.parse_args()

    conn = db.connect()
    embedder = HashEmbedder() if args.hash_embedder else get_embedder()
    tmp = Path(tempfile.mkdtemp(prefix="reindex-bench-"))
    root = tmp / "checkout"
    name = args.url.rstrip("/").rsplit("/", 1)[-1]
    repo_url = f"https://github.com/bench/{name}-{int(time.time())}"
    rid = conn.execute("INSERT INTO repos (url, full_name) VALUES (%s, %s) RETURNING id", (repo_url, f"bench/{name}")).fetchone()[0]
    results: list[dict] = []
    counter = [0]

    def run(label: str, requested: str):
        counter[0] += 1
        job = conn.execute("INSERT INTO analysis_jobs (repo_id, status) VALUES (%s, 'done') RETURNING id", (rid,)).fetchone()[0]
        status, version, _ = db.load_repo_state(conn, rid)
        r = analyze_checkout(conn, rid, job, root, sha, progress=lambda s, p: None, embedder=embedder,
                             requested_mode=requested, previous_ready=status == "ready", previous_version=version)
        conn.execute("UPDATE repos SET status='ready', last_commit_sha=%s WHERE id=%s", (sha, rid))
        row = {"run": label, "mode": r.mode, "seconds": round(r.duration_ms / 1000, 2), "files": r.files_total,
               "changed": r.files_changed, "reused": r.files_reused,
               "vectors_computed": r.index.embedded if r.index else 0, "chunks_total_in_run": r.index.chunks_total if r.index else 0,
               "timings_ms": r.timings}
        results.append(row)
        print(f"  {label:<38} {r.mode:<12} {row['seconds']:>7.2f}s  changed={row['changed']:<4} reused={row['reused']:<5} vectors={row['vectors_computed']}", flush=True)

    try:
        print(f"cloning {args.url} ...", flush=True)
        sha = clone(args.url, root)
        print(f"embedder: {embedder.name}")
        run("1 full (first run)", "full")
        conn.execute("DELETE FROM embedding_cache WHERE model = %s AND embed_hash IN (SELECT embed_hash FROM chunks WHERE repo_id = %s)",
                     (embedder.name, rid))
        run("2 full, COLD vector cache", "full")
        run("3 full, WARM vector cache", "full")
        run("4 incremental, nothing changed", "auto")
        files = pick_files(root, args.edits)
        for k, p in enumerate(files):
            edit(p, k)
        print(f"  (edited {len(files)} files: {', '.join(str(p.relative_to(root)) for p in files)})")
        run(f"5 incremental, {len(files)} files edited", "auto")
        run(f"6 full, same edited tree (warm)", "full")
        cold = next(r for r in results if r["run"].startswith("2"))["seconds"]
        warm = next(r for r in results if r["run"].startswith("3"))["seconds"]
        inc = next(r for r in results if r["run"].startswith("5"))["seconds"]
        full_after = next(r for r in results if r["run"].startswith("6"))["seconds"]
        print("\nsummary")
        print(f"  incremental ({inc}s) vs full cold ({cold}s):  {round((1 - inc / cold) * 100)}% faster")
        print(f"  incremental ({inc}s) vs full warm ({warm}s):  {round((1 - inc / warm) * 100)}% faster")
        print(f"  incremental ({inc}s) vs full on the edited tree ({full_after}s):  {round((1 - inc / full_after) * 100)}% faster")
        if args.out:
            Path(args.out).write_text(json.dumps({"url": args.url, "embedder": embedder.name, "runs": results}, indent=2))
    finally:
        conn.execute("DELETE FROM repos WHERE id = %s", (rid,))
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
