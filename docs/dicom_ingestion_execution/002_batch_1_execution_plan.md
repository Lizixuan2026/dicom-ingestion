# DICOM Ingestion — Batch 1 Execution Plan

## 1. Goal

Batch 1 exists to remove ambiguity before service code starts.

When it is done, later teams should not need to invent:

- identity rules,
- migration order,
- retry vs re-upload semantics,
- raw-byte durability behavior,
- fixture expectations,
- stage / event names.

## 2. Open now

| Workstream | Tickets / artifact | Primary output |
| --- | --- | --- |
| Schema | `A1-a` through `A1-l` | migrations for the full data model |
| Invariants | `A1-z` | executable schema invariant suite |
| Fixtures | `A2` | golden fixture corpus + manifest |
| Raw storage | `A3` | tested raw object storage contract |
| Observability | vocabulary draft | provisional stage / event vocabulary |

## 3. Recommended ownership

| Owner role | Owns | Why one owner matters |
| --- | --- | --- |
| Schema owner | `A1-a..A1-l`, `A1-z` | one person keeps cross-table invariants coherent |
| Fixture owner | `A2` | one manifest prevents every lane from inventing different expected outcomes |
| Storage owner | `A3` | byte durability is the root of retry/replay truth |
| Observability owner | vocabulary draft | someone must fix the nouns before every later lane emits different nouns |
| Eng lead / reviewer | Batch gate | one person decides whether ambiguity is actually gone |

## 4. Build order inside Batch 1

```text
A1-a -> A1-b -> A1-c -> A1-d
A1-e -> A1-f -> A1-g
A1-h / A1-i / A1-j / A1-k in parallel once their base tables exist
A1-e + A1-f -> A1-l
all A1-* -> A1-z

A2 runs in parallel from day 1
A3 runs in parallel from day 1
observability vocabulary draft runs in parallel from day 1
```

## 5. Required artifacts

| Artifact | Must contain |
| --- | --- |
| migrations | every table and uniqueness / FK rule from `011` and `012` |
| invariant suite | actual DB-backed tests for uniqueness, FK restrictions, canonical upper bound, duplicate-finding idempotency, reference-edge idempotency, series-attempt uniqueness |
| fixture README | each file, expected parse outcome, why it exists, PHI/provenance status |
| raw storage contract | `put/get/exists/delete`, checksum semantics, idempotency or compensation behavior, retry behavior |
| event vocabulary draft | stage names, event names, required structured keys, PHI exclusions, provisional metric names |

## 6. Daily check-in questions

1. Did any lane discover a missing contract?
2. Did any migration force a change to `011`?
3. Did any fixture reveal a state the schema cannot express?
4. Did storage semantics require a retry behavior not named in `012`?
5. Did two lanes choose different names for the same event?

If yes, resolve it in the source-of-truth docs before moving forward.

## 7. Batch 1 exit gate

Batch 1 is done only when all of these are true:

- schema migrations exist through `A1-l`,
- `A1-z` passes against a real database,
- `dicom_series_ingestion_attempts` exists,
- fixture corpus includes malformed, duplicate, private-tag, referenced-object, mixed-ZIP, ZIP bomb, traversal, and nested-ZIP cases,
- raw storage behavior is written down and tested,
- provisional observability vocabulary is published,
- no downstream task needs to invent a missing identity rule.

## 8. What not to start yet

- no upload controller work,
- no duplicate classifier work,
- no projection builder work,
- no query endpoint work.

Those are not blocked by lack of enthusiasm. They are blocked by facts that do not exist yet.
