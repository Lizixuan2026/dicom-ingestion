# DICOM Ingestion — Batch 2 Execution Plan (Durable Intake)

Parent documents:

- `001_full_execution_plan.md`
- `../012_migration_first_backlog.md`
- `../013_dicom_ingestion_full_feature_implementation_roadmap.md`

## 1. Goal

Make every incoming file candidate visible and durable:

- mixed uploads are exploded into candidate items,
- every candidate is tracked with a stable identity,
- unsafe or invalid package input fails loudly and explainably,
- no accepted bytes disappear between upload and intake persistence.

## 2. Tickets and order

Execution order from the roadmap:

1. `B2` candidate-item intake skeleton (first, non-negotiable)
2. `B1` upload API and `B3` scanner/ZIP safety in parallel
3. `B4` intake state transitions and `B5` intake reporting/eventing after the candidate-item contract stabilizes

## 3. Entry conditions

Batch 2 starts only after Batch 1 gate is green:

- schema invariants are frozen,
- fixture manifest contract exists,
- raw storage contract is executable,
- provisional observability vocabulary is available.

## 4. Work lanes

### Lane A — Candidate-item foundation (`B2`)

Build the durable intake core first:

- persist one record per discovered candidate file,
- keep parent upload linkage,
- capture candidate-level status + failure reason envelope,
- enforce idempotent re-processing behavior for the same source unit.

Deliverable: a stable candidate-item contract consumed by all other Batch 2 tickets.

### Lane B — Upload API (`B1`)

Integrate with Lane A contract:

- upload endpoint stores raw bytes per storage contract,
- upload acceptance produces a durable intake job reference,
- malformed requests fail with explicit API contract errors.

Deliverable: upload request -> intake job seed path is executable.

### Lane C — Scanner + ZIP safety (`B3`)

Protect the intake edge:

- recursively discover candidates in mixed archives,
- reject unsafe archive features (zip-slip/path traversal, unsupported compression edge cases, oversized entry constraints per policy),
- surface candidate-level parse and packaging failures without dropping other candidates.

Deliverable: a mixed ZIP fixture proves all safe candidates are visible, unsafe content is blocked with explicit failure semantics.

### Lane D — Intake lifecycle + reporting (`B4`, `B5`)

Start only once Lane A schema is stable.

- formalize candidate-item state transitions,
- emit lifecycle events and status reports that match vocabulary,
- ensure terminal status can be queried without log scraping.

Deliverable: intake run status is machine-readable and complete.

## 5. Merge gates (Batch 2 DoD)

Batch 2 is done when all are true:

1. Mixed ZIP fixture run proves every file candidate is either accepted as candidate-item or explicitly rejected with reason.
2. Unsafe archive input fails loudly without partial silent success.
3. Upload -> raw storage -> candidate-item persistence chain is durable and replay-safe.
4. Intake status and failure reasons are queryable through defined interfaces (not manual logs).
5. Event names and state vocabulary remain consistent with Batch 1 draft terms.

## 6. Stop-the-line triggers

Stop and resolve upstream if any happen:

- candidate-item model needs new schema fields absent from `011/012`,
- lanes diverge on status vocabulary naming,
- any path acknowledges upload but cannot prove raw/candidate persistence,
- ZIP safety policy is inferred ad hoc instead of contract-backed.

## 7. Handoff to Batch 3

Before opening Batch 3, publish:

- candidate-item schema + transition table,
- intake failure taxonomy (with representative examples),
- fixtures proving mixed package traversal and unsafe-input rejection,
- canonical contract notes for how Batch 3 (`B6/B7`) consumes accepted candidates.
