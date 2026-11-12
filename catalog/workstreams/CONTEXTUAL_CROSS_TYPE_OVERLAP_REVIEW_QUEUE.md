# Contextual Cross-Type Overlap Review Queue

## Baseline
- Base master commit: `5e71b79157966fc3f4d40f85866d7db73ee497fe`.
- Branch: `work/2026-11-12-contextual-cross-type-overlap-review-queue`.

## Gap addressed
The occurrence/overlap audit counts cross-type overlap pairs and reports only a small diagnostic sample. The full corpus currently has 1,498 cross-type pairs across ten candidate-type combinations. Counts alone do not let a reviewer inspect every pair in its original context.

## Output
- `catalog/generated/contextual_term_cross_type_overlap_review.csv`
- `catalog/generated/contextual_term_cross_type_overlap_review.json`

The CSV emits every cross-type overlap pair with:
- both candidate IDs, types, lexical text, offsets, and rule IDs;
- document, source SHA-256, tree position, block ID, and unit ID;
- overlap geometry;
- the exact source evidence window that covers both spans;
- explicit `UNREVIEWED` status and blank decision/note fields.

## Safety contract
- No candidate is merged, deleted, relabelled, or retyped.
- Same-type overlaps remain in the aggregate audit and are not misrepresented as cross-type review items.
- A pair is rejected if its source locator differs, either term does not match its evidence slice, or no evidence window covers both offsets.
- Geometric overlap is not treated as a semantic decision. Human review must decide whether the two spans represent distinct entities, a nested lexical form, or a false contextual candidate.
- The queue is a review aid, not a new relation extraction source.

## Acceptance
- Fast Python and Module CI pass.
- Full-corpus queue count and per-type-pair distribution reconcile with `contextual_term_overlap_audit.json`.
- Every exported row has exact source evidence and traceable candidate/source identity.
