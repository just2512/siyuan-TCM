# Search and Semantic Graph Workstream

Scope: SQLite schema/query behavior, FTS, graph export, and evidence traversal.

Acceptance gates:
- SQLite and graph records carry compatible source/schema revisions.
- Every graph edge resolves to a validated source evidence record.
- Query results expose source paths and block-level evidence for inspection.
- Tests cover index rebuilds, duplicate IDs, missing evidence, stale revisions, and deterministic export.
- Keep candidate status distinct from confirmed facts.
