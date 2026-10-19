"""Embed chunks that have no vector yet (e.g. the fixed-size BASELINE, for the Day 9 comparison).

    uv run python -m analyzer.embed_pending --repo 55 --strategy fixed
"""
import argparse
import logging

from . import db
from .embeddings import get_embedder
from .indexing import embed_pending


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=int, required=True)
    ap.add_argument("--strategy", choices=["ast", "fixed"], default="fixed")
    ap.add_argument("--budget", type=float, default=3600, help="seconds")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    conn = db.connect()
    cached, embedded = embed_pending(conn, get_embedder(), args.repo, (args.strategy,),
                                     lambda f: print(f"\r{f:.0%}", end="", flush=True), args.budget)
    print(f"\ndone: {cached} chunks from cache, {embedded} texts embedded")


if __name__ == "__main__":
    main()
