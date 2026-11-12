# Contextual Occurrence Rule Assignment Audit

## Baseline
- Base master commit: `fffa68d7b7cf687add569736e1a8e29d4ec94a03`.
- Branch: `work/2026-11-12-contextual-occurrence-rule-assignment-audit`.

## Gap addressed
The full-corpus contextual candidate table contains 124,017 rows, while the overlap audit reports 123,851 distinct occurrence identities. The 166-row difference must be explained rather than silently interpreted as either duplicated mentions or an error.

## Output
`catalog/generated/contextual_occurrence_rule_assignment_audit.json`

The audit groups rows by `unit_id + candidate_type + candidate_id + character_start + character_end`, verifies that all rows in a group retain the same term and source provenance, and reports:
- raw candidate rows;
- distinct source occurrence groups;
- groups matching multiple rule IDs;
- extra rule assignments beyond one per occurrence;
- per-type and per-rule-combination distributions;
- source-grounded examples.

## Safety contract
- Different source offsets always remain different occurrences.
- Multiple matching rules on the same type/span are reported as multiple rule assignments, not counted as multiple source occurrences.
- Duplicate identical occurrence/rule rows or conflicting provenance are rejected.
- No candidate is merged, deleted, retyped, or rewritten.

## Acceptance
- Fast Python and Module CI pass.
- The full-corpus report reconciles raw rows, distinct occurrence identities, and multi-rule assignments.
