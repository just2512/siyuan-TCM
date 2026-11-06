# Term Miner Workstream

Scope: corpus-driven unclassified term discovery, aggregation performance, sample evidence, source ordering, and memory bounds.

Acceptance gates:
- Preserve exact source document/revision, tree position, block ID, and character span.
- Disk-backed aggregation; bound per-document memory and expose progress counters.
- Verify sample_limit boundaries (1, 2, default), document transitions, repeated terms across units/documents, empty units, and out-of-order source documents.
- Benchmark against the current master implementation using the same corpus and record wall time, peak RSS, database size, and candidate counts.
- Do not change clinical classification semantics or merge terms automatically.
