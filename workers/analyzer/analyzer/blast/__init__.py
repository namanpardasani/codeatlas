"""Blast Radius: predict what a change will break (see BLAST_RADIUS_PLAN.md).

Everything here is pure and in-memory (no database), so the same code serves the hosted service (snapshot of the
analysed commit) and the offline evaluation (snapshot of a repo as it was at any historical commit, built only from
history before that commit, so no future information leaks into the prediction).
"""
