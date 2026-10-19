"""(Re)generate a repo's documentation from what is already in the database (no clone, no network except the LLM).

    LLM_PROVIDER=llamacpp LLM_MODEL=qwen2.5-coder-1.5b uv run python -m analyzer.docs_cli --repo 5 --max-calls 8
"""
import argparse
import logging

from . import db
from .docs.generate import generate_docs
from .llm import LLMError, get_llm


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=int, required=True)
    ap.add_argument("--max-calls", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conn = db.connect()
    sha = conn.execute("SELECT last_commit_sha FROM repos WHERE id = %s", (args.repo,)).fetchone()[0]
    try:
        llm = get_llm()
    except LLMError as e:
        print(f"no usable LLM ({e.message}); extractive summaries only")
        llm = None
    db.set_docs_status(conn, args.repo, "running")
    s = generate_docs(conn, llm, args.repo, sha or "", max_calls=args.max_calls)
    print(f"{s.targets} targets: {s.llm_calls} LLM calls (budget {s.budget}{', exhausted' if s.budget_exhausted else ''}), "
          f"{s.reused} reused, {s.cached} cached, {s.extractive} extractive, {s.guard_rejected} rejected by the guard"
          + (f"; LLM stopped: {s.llm_disabled_reason}" if s.llm_disabled_reason else ""))


if __name__ == "__main__":
    main()
