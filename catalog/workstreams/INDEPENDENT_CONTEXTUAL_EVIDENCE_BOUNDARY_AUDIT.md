# Independent Contextual Evidence Boundary Audit

## Baseline
- Base master commit: `5e71b79157966fc3f4d40f85866d7db73ee497fe`.
- Branch: `work/2026-11-12-independent-contextual-evidence-boundary-audit`.

## Gap addressed
The SQLite contextual-term audit previously imported the candidate builder's `evidence_window` function and compared the stored evidence window to that same implementation. A defect in the shared helper could therefore be reproduced by both generation and validation.

## Change
The SQLite audit now independently validates:
- exact equality between stored evidence text and the source slice at its recorded offset;
- candidate span containment inside that evidence slice;
- the configured 12-character maximum context on each side;
- absence of sentence punctuation between the candidate and either evidence-window edge;
- absence of author/book attribution markers between the candidate and either evidence-window edge.

The auditor no longer imports or calls the builder's evidence-window function.

## Safety contract
- Candidate IDs, labels, types, offsets, evidence, and relations are not rewritten.
- This is a validation hardening change only.
- A failed boundary check rejects the audit; it does not silently trim or repair evidence.

## Acceptance
- Fast Python and Module CI pass.
- Unit tests independently reject sentence-boundary and author-attribution crossings.
- Full-corpus SQLite contextual-term audit rechecks every candidate against its resolved source block.
