# Entity Mention Cross-Type Overlap Review

## Baseline
- Base master commit: `fffa68d7b7cf687add569736e1a8e29d4ec94a03`.
- Branch: `work/2026-11-12-entity-mention-cross-type-overlap-review`.

## Gap addressed
The existing entity-mention overlap audit validates all 421,850 source spans and reports aggregate overlap classes, but its examples are capped. Full-corpus output contains 27,419 nested FORMULA/HERB pairs and 2,677 other nested cross-type pairs, plus two partial FORMULA/HERB overlaps. Aggregate counts do not provide a reviewable record for every pair.

## Output
- `catalog/generated/entity_mention_cross_type_overlap_review.csv`
- `catalog/generated/entity_mention_cross_type_overlap_review.json`

Every cross-type overlap pair is exported with both mention IDs, entity types, matched text, original offsets, document, source SHA-256, tree position, block ID, unit ID, and a bounded source excerpt. A formula-herb `relation_id` is attached only when that exact mention pair is already linked by a relation candidate.

## Safety contract
- Same-type overlaps remain in the existing aggregate audit and are not added to this cross-type queue.
- Every cross-type overlap is retained for semantic review; containment alone never removes or retypes a mention.
- Every mention offset is revalidated against the exact source block before queue creation.
- Relation links are exact mention-ID pairs; nearby-block relation endpoints are not inferred from lexical similarity.
- All rows begin `UNREVIEWED`; no candidate or relation is modified.

## Acceptance
- Fast Python and Module CI pass.
- Full-corpus queue totals and type-pair distribution reconcile with `entity_mention_overlap_audit.json`.
- Every queue row has a resolvable source locator and exact mention slices.
