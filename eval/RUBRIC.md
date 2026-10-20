# Grading rubric (used by the LLM judge AND by the human spot-check)

Grade each answer on three independent dimensions, 0-2. Judge only what is written; do not reward length or style.

**correctness** - does the answer say what the ground-truth notes say?
- 2: contains the key facts of the notes and nothing that contradicts them
- 1: partly right: misses a key fact, or is vague, or adds a wrong minor detail
- 0: wrong, off-topic, or says nothing useful

**groundedness** - is every claim backed by the provided code excerpts?
- 2: every claim is visible in the excerpts
- 1: mostly supported, but one or two claims go beyond the excerpts (general knowledge, guesses)
- 0: key claims are not in the excerpts (invented functions, behaviour, files)

**citation_validity** - do the cited passages (the [C#] labels and files named) actually support the sentences they are attached to?
- 2: citations point at the passages that support the claims
- 1: some citations are wrong, missing for key claims, or only loosely related
- 0: citations are wrong or absent for the answer's main claims
- if the answer has no citations at all because it correctly refused: grade 2; if it makes claims with no citations: grade 0

A refusal ("I couldn't find this in the repo.") is correct only for questions marked unanswerable.
