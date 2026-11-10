# Parallel Workstream Integration Protocol

This protocol keeps independent work moving without allowing unvalidated candidates or generated artefacts onto `master`.

## Branch contract

- Every active workstream branch starts from the same recorded `master` SHA.
- Use `work/YYYY-MM-DD-<workstream>` for implementation branches and `integration/YYYY-MM-DD-<purpose>` for integration-only changes.
- One branch owns one bounded code surface. Avoid concurrent edits to the same production file.
- Do not commit implementation changes directly to `master`. The catalogue bot may publish generated files after the full master workflow passes.
- Do not force-push or silently reuse stale branches. A branch more than one integration batch behind must be refreshed/rebased and its diff re-audited before a PR is accepted.

## Active workstream ownership

| Workstream | Owned surface | Required evidence |
|---|---|---|
| Context taxonomy | `build_contextual_term_candidates.py` and its tests | Positive/negative cue fixtures, overlapping spans, exact source offsets, repeated occurrences |
| Relation extraction | `build_contextual_relation_candidates.py`, coverage audit and tests | Predicate direction, explicit predicate between endpoints, endpoint identity, negation, sentence and attribution boundaries |
| Search graph | SQLite query/index, graph export, smoke tests | Table/metadata count equality, FTS, zero-row and populated predicate queries, graph/SQLite equality, resolvable evidence |
| Term provenance | Entity mention extraction, overlap audit and tests | Occurrence-derived IDs, distinct repeated spans, source revision and block locator, exact source slice |

## CI and integration gates

1. Every implementation branch must pass both Fast Python CI and Module CI.
2. Pull requests target `master`; review the changed-file list for ownership violations and compare the branch against current `master`.
3. Do not merge a stale or diverged branch merely because its old CI passed.
4. Keep generated catalogue outputs out of implementation PRs. The master-only full-corpus workflow is the integration gate and generates SQLite, graph and audit artefacts from one source SHA.
5. Integrate a coherent batch only after all participating branch checks pass. Avoid intermediate master commits that cancel the full-corpus build while the batch is still being integrated.
6. The final master run must pass source tests, generation, endpoint/evidence validation, SQLite smoke checks, graph consistency, review-queue generation and catalogue validation before generated artefacts are accepted.

## Zero-result policy

A relation predicate with zero candidates is a valid result when the coverage audit shows why endpoints or explicit predicates are absent, and the SQLite query returns an empty result for that predicate. Never widen sentence windows, cross source-attribution boundaries, infer from co-occurrence, or optimize for candidate count.

## Completion record

Each workstream PR must state:
- base master SHA and final head SHA;
- files owned and files changed;
- CI run IDs and conclusions;
- before/after candidate counts by predicate, including zero counts;
- endpoint, overlap and source-offset checks;
- unresolved findings and explicit non-goals.
