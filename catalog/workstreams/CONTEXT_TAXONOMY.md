# Context Taxonomy Workstream

Scope: contextual candidate typing for symptoms, pulse, tongue, syndromes, and treatment methods.

Acceptance gates:
- Every occurrence of a mined candidate term is classified against the full source corpus; bounded discovery samples must never cap occurrence coverage.
- Every occurrence retains exact source evidence and source identity, including character start/end offsets.
- Repeated occurrences of the same term/type/rule in one knowledge unit remain distinct rows.
- Context rules are explicit, inspectable, and non-diagnostic.
- Prefix-only cues must immediately precede the candidate span (allowing at most two whitespace/punctuation characters); candidates must not classify themselves or borrow cues from distant text.
- Cue patterns must include the complete grammatical forms used by supported relation predicates (for example, `辨证为`, `辨证属`, `治法为`, `当以`).
- Ambiguous or overlapping contexts remain candidates with transparent multi-label/unknown handling.
- Tests cover positive, negative, overlapping, punctuation-boundary, and cross-block cases.
- Do not modify original notes or infer clinical equivalence.
