# SQLite Source Locator Integrity Workstream

## Baseline and ownership
- Baseline: `17282ac24403d91a30ba9b18b58a5c98bb0975d2` (zero-yield graph audit integration head).
- Branch: `work/2026-11-12-sqlite-source-locator-integrity`.
- Owned files: `tools/audit_sqlite_source_locator_integrity.py`, its unit tests, and full-corpus workflow invocation/artifact wiring.

## Finding
Semantic graph validation and SQLite audits resolve source evidence through the composite locator `document + source_sha256 + tree_position + block_id`. Some lookups use `LIMIT 1`; if the SQLite content table contains duplicate rows for one locator, the selected source row is ambiguous even when one matching slice happens to validate.

## Change
- Add an independent full-table audit for source locator uniqueness.
- Verify each source row has non-empty document, source hash and tree position.
- Verify the stored character count equals the actual source text length.
- Persist a versioned JSON report and upload it with the other SQLite/graph audit evidence.
- Do not alter source rows, candidate extraction, identity rules, or graph semantics.

## Acceptance
- Unique locator fixtures pass, including nullable block IDs as normalized empty values.
- Duplicate locator groups fail even if duplicate text is identical.
- Missing source identity and character-length drift fail.
- Full-corpus workflow must produce a zero-duplicate, zero-malformed report before the build can publish artifacts.
