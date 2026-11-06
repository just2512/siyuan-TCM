# Relation Extraction Workstream

Scope: explicit relation candidates, canonical predicates, evidence validation, and source provenance.

Acceptance gates:
- Subject/object mentions must be grounded in the same permitted source context.
- Predicate vocabulary and direction are explicit and versioned.
- Distinguish co-occurrence from asserted relation; reject unsupported cross-document joins.
- Tests cover direction, negation, scope boundaries, repeated mentions, and provenance mismatch.
- No automatic diagnosis or clinical recommendation.
