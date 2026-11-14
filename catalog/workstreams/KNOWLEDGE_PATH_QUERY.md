# Source-Grounded TCM Knowledge Path Query

## Purpose

Expose the existing passage, occurrence, SQLite relation, and semantic-graph work as a practical reverse-navigation query. A user can start with a symptom, formula, herb, theory term, acupoint, or acupuncture technique and inspect the exact source passages and adjacent records.

This is a navigation and evidence-retrieval feature. It does not diagnose, recommend treatment, establish efficacy, or infer that two terms are clinically equivalent.

## Query

Run from the repository root after generating the local catalogue and SQLite database:

    python tools/search_classical_knowledge_paths.py --query 恶寒 --term-type SYMPTOM --source-work SHANG_HAN_LUN

Other examples:

    python tools/search_classical_knowledge_paths.py --query 桂枝汤 --term-type FORMULA
    python tools/search_classical_knowledge_paths.py --query 头痛 --term-type SYMPTOM --source-work JIN_GUI_YAO_LUE
    python tools/search_classical_knowledge_paths.py --query 腠理 --term-type CLASSICAL_THEORY
    python tools/search_classical_knowledge_paths.py --query 足三里 --term-type ACUPOINT --document-role CLASSICAL_CHAPTER

Supported source-work filters are SHANG_HAN_LUN, JIN_GUI_YAO_LUE, HUANG_DI_NEI_JING, and ZHEN_JIU_DA_CHENG. The role filter can separate CLASSICAL_CHAPTER, FORMULA_REFERENCE, COMMENTARY, SOURCE_NOTE, and AUXILIARY_NOTE.

## Returned path

Each matched occurrence returns:

- Its exact occurrence ID, term type, matched text, original block offsets, passage-relative offsets, and a check that the recovered source slice equals the matched term.
- Source work, document role, title, chapter path, document path, source SHA, tree position, block ID, passage ID, and the exact passage text.
- Other term occurrences in that same passage, including formulas, herbs, symptom/syndrome candidates, classical-theory terms, acupoints, and acupuncture techniques.
- Existing same-passage occurrence links touching the matched occurrence.
- Explicit formula-herb and symptom/syndrome/treatment/formula relation candidates connected to any occurrence in the passage, with their own evidence locator and unresolved state.
- Existing native SiYuan block references, when present.

Repeated appearances are independent results. The query is lexical substring matching; it does not automatically merge aliases or normalize distinct source occurrences into one entity.

## Relation semantics

| Output section | Meaning |
| --- | --- |
| navigational_links | Two separate occurrences in one exact passage. Navigation only, not a clinical assertion. |
| formula_herb_candidates | Formula/herb extraction candidate with source evidence. Its unresolved state is preserved. |
| contextual_relation_candidates | A relation extracted from an explicit predicate pattern. Its unresolved state and predicate evidence are preserved. |
| document_references | Existing native SiYuan block reference, not an inferred cross-book link. |
| passage_terms | Terms that occur in the same passage. Co-occurrence is not treatment or theory attribution. |

A symptom and formula found in one passage are not automatically a proven prescription relationship. A formula and herb co-occurring in commentary are not automatically the canonical formula composition. The source role and the explicit relation evidence must be inspected.

## Acceptance

The query tests cover:

1. Repeated identical symptom text at different offsets remains separate.
2. Source-work filtering distinguishes Shanghan Lun and Zhenjiu Dacheng passages.
3. A source-grounded formula-herb candidate and symptom-syndrome candidate can be traced from a symptom query.
4. Symptom-to-acupoint and symptom-to-technique passage links are returned as navigation-only links.
5. The source locator, exact recovered term span, source role, and native reference are retained.
6. Empty queries, invalid limits, and databases missing passage tables fail explicitly.

The query result is bounded by the existing generated index. It does not claim complete classical-text coverage or supply cross-book links where the source notes contain no native reference.
