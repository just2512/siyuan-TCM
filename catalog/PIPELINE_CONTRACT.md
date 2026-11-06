# Knowledge Index Pipeline Contract

## Branch topology

- `master`: production source of truth. Full-corpus generation and generated-catalog publication run only here.
- `integration/knowledge-index`: integration staging branch. Changes from work branches are combined here before promotion to master.
- `work/term-miner`: corpus term mining, aggregation, provenance spans, and performance.
- `work/context-taxonomy`: contextual term taxonomy (symptoms, pulse, tongue, syndrome, treatment).
- `work/relation-extraction`: explicit relation extraction and provenance validation.
- `work/search-graph`: SQLite search, graph export, query APIs, and evidence traversal.

All work branches start from the same baseline commit. Work branches must not publish generated corpus artifacts to master. No force-pushes or history rewrites.

## Data and evidence invariants

1. Original note content is immutable input. Generated indexes are derived artifacts.
2. Every extracted term, entity mention, or relation must retain source document, source SHA/revision, tree position, block ID, and exact character span/evidence text where applicable.
3. Candidate states must remain explicit (for example `UNCLASSIFIED_TERM_CANDIDATE`, `LEXICAL_ID_ONLY`, `UNRESOLVED_CANDIDATE`). Extraction is not medical interpretation or user approval.
4. Never merge lexical variants or infer clinical equivalence without an explicit, separately versioned rule.
5. SQLite and semantic graph outputs must carry the same source revision and schema/contract version. Graph records must be traceable to source evidence and corresponding index records.
6. A generated catalog may be published only when the checked-out source SHA still equals the current `master` SHA. Stale builds must exit without publishing.

## CI tiers

- L1 fast CI: Python syntax compilation and unit tests; runs on work branches and pull requests. No corpus-wide generation.
- L2 module CI: branch-scoped tests and static checks; runs independently per work branch. It must not write to `catalog/generated` on master or publish artifacts as production data.
- L3 full-corpus CI: `.github/workflows/build-catalog.yml`, triggered only by master pushes or manual dispatch. It builds the full catalogue, validates provenance and graph consistency, and publishes generated output only after the stale-SHA guard.

## Integration protocol

1. Implement each workstream on its assigned branch.
2. Keep changes within the workstream's ownership boundary. Shared schema changes require updating this contract and compatibility tests.
3. Run L1/L2 before merging into `integration/knowledge-index`.
4. Integrate compatible workstreams in batches; resolve shared schema changes once, then run integration tests.
5. Promote the integration batch to `master` only after L1/L2 pass and the full-corpus L3 run passes.
6. Never merge generated output from an older source SHA over newer master content.

## Ownership boundaries

| Workstream | Primary ownership |
| --- | --- |
| term-miner | `tools/build_unclassified_term_candidates.py` and term-mining tests |
| context-taxonomy | `tools/build_contextual_term_candidates.py` and contextual term tests |
| relation-extraction | `tools/build_*relation_candidates.py` and relation provenance tests |
| search-graph | `tools/build_siyuan_search_db.py`, `tools/export_semantic_graph.py`, and query/graph tests |

Shared files (schemas, common evidence utilities, workflow contracts) require coordination through the integration branch. Avoid concurrent edits to the same file; use small contract-first changes where shared interfaces are unavoidable.
