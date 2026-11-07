# Context Taxonomy Workstream

Scope: contextual candidate typing for symptoms, pulse, tongue, syndromes, and treatment methods.

Acceptance gates:
- Every occurrence of a mined candidate term is classified against the full source corpus; bounded discovery samples must never cap occurrence coverage.
- Every occurrence retains exact source evidence and source identity, including character start/end offsets.
- Repeated occurrences of the same term/type/rule in one knowledge unit remain distinct rows.
- Context rules are explicit, inspectable, and non-diagnostic.
- Ambiguous or overlapping contexts remain candidates with transparent multi-label/unknown handling.
- Tests cover positive, negative, overlapping, punctuation-boundary, and cross-block cases.
- Do not modify original notes or infer clinical equivalence.
