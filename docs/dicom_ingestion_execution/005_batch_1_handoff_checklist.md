# DICOM Ingestion — Batch 1 Handoff Checklist

## 1. Purpose

This is the handoff from foundation work to intake work.

Batch 2 should inherit a stable floor, not a Slack thread full of tribal knowledge.

## 2. Handoff packet

| Item | Handed to Batch 2 |
| --- | --- |
| schema summary | final table list, migration order, key invariants |
| invariant suite output | proof that the schema rules actually pass |
| fixture manifest | file list, expected outcomes, fixture usage notes |
| raw storage contract | interface, failure semantics, retry behavior |
| observability vocabulary draft | stage names, event names, required keys, PHI exclusions |
| open issues | explicit list, ideally empty |

## 3. Batch 2 readiness questions

- [ ] Can `B2` persist a raw package without guessing storage semantics?
- [ ] Can `B1` create a job without guessing idempotency fields?
- [ ] Can `B3` scan fixtures that already cover unsafe archives?
- [ ] Can `B4` and `B5` share a candidate-item contract without inventing a second version?
- [ ] Can every lane emit the same stage names from day one?

## 4. If the answer is no

Route the issue back to the correct source:

| Problem | Fix upstream in |
| --- | --- |
| missing schema rule | `011`, then `012` |
| missing task acceptance | `012` |
| unclear construction order | `013` |
| unclear operating sequence | `014` |
| unclear Batch 1 execution artifact | this folder |

## 5. Sign-off

Batch 1 is handed off when:

- [ ] schema owner signs off,
- [ ] fixture owner signs off,
- [ ] storage owner signs off,
- [ ] observability owner signs off,
- [ ] eng lead confirms no unresolved ambiguity blocks `B2`.

After this, open Batch 2. Not before.
