# Semantic Graph Validation Report Workstream

## Baseline and ownership
- Immutable master baseline: `934f8131458066a3f196d7d0f66e3cb15fb90dcf`
- Branch: `work/2026-11-12-semantic-graph-validation-report`
- Owned files: `tools/export_semantic_graph.py`, `tools/test_export_semantic_graph.py`
- No workflow-file edits in this workstream; pipeline wiring belongs to a later integration change after the current SQLite batch.

## Finding
The full-corpus workflow validates graph nodes, relation edges, contextual term candidates, contextual relation edges, endpoint identity and source evidence. The validator returns exact validated counts, but the workflow only retains them in transient job logs. A committed machine-readable validation report makes graph/SQLite parity independently reviewable alongside `search_index_smoke.json`.

## Change
- Add optional `--report` output to `export_semantic_graph.py`.
- Persist the validator's returned entity-node, relation-edge, contextual-term and contextual-relation counts as versioned JSON.
- Keep validation behavior unchanged; report writing happens only after validation succeeds.
- Add a unit test for schema and zero-valued contextual relation counts.

## Acceptance
- Existing graph validation tests continue to pass.
- Report is written only after successful validation.
- Zero edge counts remain explicit zeros, not missing keys.
- No candidate extraction, graph schema, or source-boundary semantics change.
