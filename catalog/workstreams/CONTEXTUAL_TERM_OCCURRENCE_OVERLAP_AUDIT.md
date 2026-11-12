# Contextual Term Occurrence and Overlap Audit

## Baseline
- Base integration head: `17282ac24403d91a30ba9b18b58a5c98bb0975d2`.
- Branch: `work/2026-11-12-contextual-term-overlap-audit`.

## Purpose
The lexical candidate ID identifies vocabulary, not a unique occurrence. This audit independently enumerates occurrence identities by unit, candidate type, candidate ID and source offsets. It reports repeated lexical forms at distinct offsets and overlapping windows (exact, nested and partial).

## Safety contract
- Distinct offsets for the same lexical term remain distinct occurrence records.
- Same-occurrence rows repeated for the same rule are rejected.
- Overlaps are diagnostic evidence only. The audit does not merge, delete, or reclassify candidates.
- Cross-type and same-type overlaps are both retained for semantic review.
- No relation extraction, candidate vocabulary, source offsets, or entity typing rules are changed.

## Full-corpus artifact
`catalog/generated/contextual_term_overlap_audit.json`

## Acceptance
Fast Python and Module CI pass. On full-corpus execution, inspect occurrence totals and overlap examples alongside the entity mention overlap audit. Any semantic decision to collapse or preserve an overlapping pair must be grounded in entity meaning, not merely string containment.
