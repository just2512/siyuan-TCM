# Contextual Relation Zero-Yield Diagnostic Workstream

## Baseline and ownership
- Initial shared master baseline: `934f8131458066a3f196d7d0f66e3cb15fb90dcf`
- Work branch: `work/2026-11-12-contextual-relation-zero-yield-diagnostic`
- Owned files: `tools/audit_contextual_relation_coverage.py`, `tools/test_audit_contextual_relation_coverage.py`
- No production relation extraction rules or predicate vocabulary are changed.

## Finding
The full-corpus baseline scans 236,987 source units and reports zero extracted candidates for all three contextual predicates. Existing diagnostics record typed endpoint spans but omit exact predicate marker offsets, making it harder to determine whether the marker lies before, inside, or after the ordered endpoint pair.

## Change
- Include exact source-absolute offsets and text for every predicate marker in each source-grounded diagnostic example.
- Keep existing marker, endpoint, order, negation, attribution and eligibility rules unchanged.
- Version the report schema and test marker text against exact source slices.

## Acceptance
- Fast Python CI and Module CI pass.
- Every emitted marker span resolves to the exact source substring.
- No candidate count, predicate vocabulary, sentence window, endpoint ordering, or extraction threshold is changed.
- Zero-yield diagnostics remain diagnostics, not permission to broaden extraction.
