# SQLite Relation Audit Contract

The full-corpus build must validate both relation tables after SQLite creation and before semantic-graph export.

## Formula-herb relations

Run `tools/audit_sqlite_formula_herb_relations.py --db catalog/generated/siyuan_search.sqlite3`.

The audit scans every `semantic_relation_candidates` row and requires:
- metadata count equals the table row count;
- relation IDs match the canonical endpoint-mention/evidence/rule identity;
- subject and object resolve to source-backed mentions with FORMULA/HERB direction and exact text;
- the subject remains in the same source document and source revision, while the object resolves to the evidence unit;
- both endpoint spans and the complete evidence span match exact source text;
- evidence is contained in one source sentence.

## Contextual relations

Run `tools/audit_sqlite_contextual_relations.py --db catalog/generated/siyuan_search.sqlite3`.

The audit scans every `contextual_relation_candidates` row and requires:
- metadata count equals the table row count;
- all three supported predicates are reported, including zero-row predicates;
- relation IDs match endpoint candidate IDs, offsets, unit identity and evidence offsets;
- each endpoint resolves to the exact typed SQLite candidate occurrence;
- predicate text is present between ordered endpoints and is not negated;
- evidence matches one complete source sentence and does not cross an author/source-attribution boundary.

## Interpretation

These checks validate storage identity and provenance; they do not assert clinical truth or authorize a relation. Zero candidates remain valid when the independent coverage audit explains the missing endpoint or predicate evidence. No candidate generation, count, or source content is changed by these audits.
