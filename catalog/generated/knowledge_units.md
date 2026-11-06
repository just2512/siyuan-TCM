# Machine-readable knowledge units

- Schema version: 1.0.0
- Units: 236987
- Unique unit IDs: 236987

## Unit types

- SECTION_HEADING: 11861
- SOURCE_HTML_TEXT: 1
- SOURCE_LIST_ITEM: 754
- SOURCE_PARAGRAPH: 218947
- SOURCE_TABLE_CELL: 5424

## Contract

- Each unit preserves the exact source text and a separate whitespace-normalized search form.
- Every unit carries the source document, SHA-256, block ID, tree position and heading context.
- IDs are deterministic for the same source revision and block location.
- semantic_status remains UNCLASSIFIED and assertion_status remains NOT_INTERPRETED; this stage does not infer medical meaning.
- Original .sy files are read-only; this output is a derived interchange format.

## Output

- knowledge_units.jsonl.gz: UTF-8 JSON Lines compressed with deterministic gzip metadata.
