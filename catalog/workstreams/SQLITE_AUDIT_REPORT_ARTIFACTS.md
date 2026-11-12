# SQLite Audit Report Artifacts Workstream

## Baseline and ownership
- Shared master baseline: `67dd57fcd6c3c07441c6523de80931481adefb01`
- Branch: `work/2026-11-12-sqlite-audit-report-artifacts`
- Owned files: four SQLite audit CLI scripts, `tools/audit_report.py`, its test, and `.github/workflows/build-catalog.yml`.
- No schema, candidate generation, relation extraction, or source-boundary behavior changes.

## Finding
The SQLite audit scripts return detailed machine-readable dictionaries, but the full-corpus workflow only writes them to transient job logs. The committed smoke report contains table counts and query checks, but not all per-row source-audit counts and endpoint/provenance results.

## Change
- Add optional `--output` to entity mention, contextual term, contextual relation, and formula-herb SQLite audit commands.
- Persist each result as a versioned JSON report under `catalog/generated`.
- Upload the reports with the SQLite and graph artifacts.
- Preserve explicit zero counts and existing nonzero/zero query validation behavior.

## Acceptance
- Unit tests cover the shared report writer and explicit zero values.
- Fast Python CI and Module CI pass.
- Full-corpus workflow writes all four reports only after their corresponding audits pass.
- No generated report is committed as implementation code; it remains a build output/artifact.

## Report paths
- `catalog/generated/sqlite_entity_mention_audit.json`
- `catalog/generated/sqlite_contextual_term_audit.json`
- `catalog/generated/sqlite_contextual_relation_audit.json`
- `catalog/generated/sqlite_formula_herb_relation_audit.json`
