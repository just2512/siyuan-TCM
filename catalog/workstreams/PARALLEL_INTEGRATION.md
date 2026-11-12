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

## Two-tier integration model

1. Record one immutable `master` baseline SHA for the whole batch.
2. Create every independent `work/YYYY-MM-DD-<workstream>` branch from that same baseline, not from another work branch.
3. Each work branch owns one bounded code surface and opens a PR into the batch's `integration/YYYY-MM-DD-<purpose>` branch. The integration branch is the temporary batch target; it is not a release branch.
4. Workstream PRs may be merged into the integration branch only after their own Fast Python CI and Module CI pass and their changed-file ownership is reviewed.
5. After all workstreams are integrated, run Fast Python CI and Module CI on the complete integration head. Review the combined diff against the recorded master baseline; reject generated catalogue outputs and unrelated files.
6. Open exactly one batch PR from the integration branch to `master`. The integration PR must state the baseline SHA, final integration SHA, constituent workstream PRs, CI run IDs, candidate counts by predicate (including zeros), provenance checks and unresolved findings.
7. If `master` advances before the batch PR merges (including a catalogue-bot commit), refresh the integration branch from the new master with a normal merge/rebase, re-audit the complete diff, and rerun both CI workflows. Never force-push or merge a stale diff merely because earlier checks passed.
8. Merge the batch PR only after its current-head Fast Python CI and Module CI pass and the previous master full-corpus workflow is complete. This avoids cancelling or interleaving full-corpus builds.
9. The merge to `master` triggers the single full-corpus release gate. Accept the batch only after generation, source/endpoint validation, SQLite smoke checks, graph/SQLite consistency, review-queue generation and catalogue validation all pass, and the catalogue bot has committed the generated outputs.

## CI and integration gates

- Every workstream branch must pass both Fast Python CI and Module CI before integration.
- The integration head must pass both workflows after the complete batch is assembled.
- The batch PR to `master` must pass both workflows again on its current head.
- Keep generated catalogue outputs out of workstream and integration implementation diffs. The master-only full-corpus workflow generates SQLite, graph and audit artefacts from one source SHA.
- Do not commit implementation changes directly to `master`. The catalogue bot may publish generated files only after the full master workflow passes.
- Do not merge a stale or diverged branch merely because its old CI passed. A branch more than one integration batch behind must be refreshed and its diff re-audited before acceptance.

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
