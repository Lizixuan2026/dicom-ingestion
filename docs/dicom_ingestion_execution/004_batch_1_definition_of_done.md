# DICOM Ingestion — Batch 1 Definition of Done

## 1. Decision rule

Batch 1 is not complete when the tickets are "mostly merged." It is complete when the next batch can start without inventing missing facts.

## 2. Required evidence

### Schema

- [ ] migrations `A1-a` through `A1-l` exist
- [ ] migration order works forward and backward
- [ ] canonical observation constraints exist
- [ ] duplicate-finding uniqueness shapes exist
- [ ] reference-edge natural key exists
- [ ] `dicom_series_ingestion_attempts` exists

### Invariants

- [ ] `A1-z` runs against a real database
- [ ] uniqueness tests pass
- [ ] FK restriction tests pass
- [ ] canonical upper-bound tests pass
- [ ] duplicate-finding retry idempotency tests pass
- [ ] reference-edge rebuild idempotency tests pass
- [ ] series-attempt uniqueness tests pass

### Fixtures

- [ ] fixture corpus is committed
- [ ] fixture README explains expected result for every file
- [ ] PHI / provenance status is documented
- [ ] corpus includes valid, malformed, duplicate, private-tag, referenced-object, ZIP bomb, traversal, nested-ZIP, and mixed-ZIP cases

### Raw storage

- [ ] contract exposes `put/get/exists/delete`
- [ ] checksum semantics are explicit
- [ ] write behavior is either idempotent or has compensation rules
- [ ] retry from stored bytes is possible in principle
- [ ] tests prove the contract, not just the happy path

### Observability vocabulary

- [ ] provisional stage names exist
- [ ] provisional event names exist
- [ ] required structured keys exist
- [ ] PHI exclusions are written down
- [ ] later `C7` implementation has a named artifact to finalize against

## 3. Required review

Before Batch 1 closes, one reviewer should answer all five questions:

1. Can Batch 2 create an upload package without inventing a new table or state?
2. Can Batch 2 test mixed uploads using fixtures that already exist?
3. Can future retry/replay work rely on raw bytes being durable?
4. Can later duplicate / series-conflict work rely on the schema without patching its identity model?
5. Can later observability work use an existing vocabulary instead of naming events ad hoc?

If any answer is "not yet," Batch 1 is not done.

## 4. Non-goals for Batch 1

- no public API behavior,
- no user-visible ingest flow,
- no duplicate classification,
- no projection rebuild,
- no dashboards yet.

Trying to sneak those in does not make Batch 1 more complete. It just gives the foundation lane a side quest.
