"""Offline evaluation of Blast Radius on real regressions (BLAST_RADIUS_PLAN.md, Phase 7).

Lives apart from the hosted service: it reads full clones of a fixed list of open-source repos (eval/blast/repos.json)
and never runs their code. The optional coverage experiment that does run tests is in eval/blast/coverage/ and only
inside a locked-down container.

  python -m analyzer.blast.evaluation mine       # bug-fix commits + SZZ -> eval/blast/dataset/pairs.json
  python -m analyzer.blast.evaluation sample     # random pairs for manual validation -> validation sheet
  python -m analyzer.blast.evaluation run        # experiment, baselines, ablations -> eval/results/blast_*.json
"""
