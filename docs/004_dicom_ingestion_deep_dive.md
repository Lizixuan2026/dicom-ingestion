# DICOM Ingestion Deep Dive — Source-Level Follow-up

## Why this document exists

The previous research round established a useful direction, but several conclusions were still too coarse. This follow-up tightens the evidence around five questions that matter directly for a **non-PACS DICOM ingestion module** inside a broader data platform:

1. How should receive, persist, index, and query be separated?
2. Where should platform-specific object mapping live?
3. How should duplicate handling be modeled?
4. What referential metadata must be preserved for derived objects?
5. What does a mature implementation persist in its fast query index versus the full DICOM payload?

This document only states what can be supported from the cloned source trees currently present under `research/repos/`.

---

## 1. Dicoogle: the important pattern is not "plugin architecture"; it is the execution split

### What the source actually does

Dicoogle separates the ingestion lifecycle into distinct layers:

- **Storage abstraction**: `StorageInterface` defines URI-scheme-based storage with recursive `at(...)`, exact `get(...)`, `store(...)`, `remove(...)`, and `list(...)` operations.
  - Evidence: `research/repos/dicoogle/sdk/src/main/java/pt/ua/dicoogle/sdk/StorageInterface.java`
- **Filesystem traversal**: `DefaultFileStoragePlugin` converts a directory URI into an iterator of `StorageInputStream`s via recursive file iteration.
  - Evidence: `research/repos/dicoogle/dicoogle/src/main/java/pt/ua/dicoogle/plugins/DefaultFileStoragePlugin.java`
- **Receive → persist → enqueue**: on C-STORE, `DicomStorage.onCStoreRQ(...)` reads the dataset, writes provenance into file meta information, delegates persistence to storage plugins, then enqueues only the resulting URI for later indexing.
  - Evidence: `research/repos/dicoogle/dicoogle/src/main/java/pt/ua/dicoogle/server/DicomStorage.java`
- **Queue-based indexing**: `IndexQueueWorker` is a dedicated worker that drains a priority queue and dispatches indexing separately from storage.
  - Evidence: `research/repos/dicoogle/dicoogle/src/main/java/pt/ua/dicoogle/server/IndexQueueWorker.java`
- **Task-oriented indexing**: `PluginController.index(...)` resolves storage from URI scheme, turns the location into `StorageInputStream`s, asks each indexer to create a `Task<Report>`, dispatches those tasks, and tracks them independently.
  - Evidence: `research/repos/dicoogle/dicoogle/src/main/java/pt/ua/dicoogle/plugins/PluginController.java`
- **Read model construction after query**: `DIMGeneric` does not participate in ingestion. It materializes patient/study/series/instance hierarchy from `SearchResult.extraData` after query execution.
  - Evidence: `research/repos/dicoogle/sdk/src/main/java/pt/ua/dicoogle/sdk/datastructs/dim/DIMGeneric.java`
  - Evidence: `research/repos/dicoogle/dicoogle/src/main/java/pt/ua/dicoogle/server/SearchDicomResult.java`

### Why this matters for our design

The strong lesson is not “build plugins.” The stronger lesson is:

> **Do not collapse raw file storage, metadata extraction, secondary indexing, and user-facing hierarchy materialization into one synchronous write path.**

For our ingestion module, this supports a staged design:

1. accept file / batch
2. persist immutable source bytes
3. parse cheap metadata
4. enqueue deeper enrichment / indexing
5. expose query projections separately from canonical storage

That separation gives us retries, observability, backfills, and re-indexing without re-uploading raw DICOM bytes.

---

## 2. XNAT: it proves configurable identity mapping, but the full Session/Scan builder path is not in this repository

### What the source actually proves

The checked-in XNAT source clearly shows that **routing/identity assignment is configurable and receiver-aware**:

- `DbBackedProjectIdentifier` applies a chain of extractors over DICOM headers to resolve a project.
- `Xnat15DicomProjectIdentifier` uses tags such as `PatientComments`, `StudyComments`, `AdditionalPatientHistory`, `StudyDescription`, and `AccessionNumber` as candidate project signals, plus dynamic config rules.
- `XnatDefaultPerReceiverDicomObjectIdentifier` and `RoutingExpressionFromInstanceProvider` add per-receiver routing expressions for project / subject / session identification.
- `DicomSCPManager.getDicomObjectIdentifier(aeTitle, port)` selects a receiver-specific identifier at runtime.
  - Evidence: files under `research/repos/xnat/web/src/main/java/org/nrg/dcm/id/`
  - Evidence: `research/repos/xnat/web/src/main/java/org/nrg/dcm/scp/DicomSCPManager.java`

The repo also proves **header-only parsing is intentional**, not incidental:

- `DicomUtils.getMaxStopTagInputHandler()` reads all useful metadata only up to `PixelData`.
- `DicomUtils.read(...)` rejects candidates that do not contain `SOPClassUID`.
  - Evidence: `research/repos/xnat/libs/dicomtools/src/main/java/org/nrg/dicomtools/utilities/DicomUtils.java`

### What is not fully proven from the checked-in repo

The actual concrete transformation from parsed DICOM into final XNAT Session/Scan objects is not fully visible in the checked-in tree because XNAT depends on an external `SessionBuilders` artifact:

- `research/repos/xnat/gradle/libs.versions.toml`
- `research/repos/xnat/parent/pom.xml`

So the defensible conclusion is narrower than the earlier draft implied:

> **XNAT strongly supports a separate, configurable identity/routing layer before platform-object construction; this checkout does not by itself fully expose the downstream Session/Scan builder internals.**

### Why this matters for our design

For us, that still supports a very specific boundary:

- **DICOM identity extraction** should produce a neutral ingestion record.
- **Platform binding** should be a separate configurable layer that decides how Study/Series/Patient-like concepts map into our own data model.

This prevents the ingestion parser from becoming permanently contaminated by one business interpretation of “project,” “subject,” or “session.”

---

## 3. Posda: duplicate handling is an explicit curation workflow, not a hidden import side effect

### What the source actually does

Posda treats duplicate handling as a durable workflow with its own queries and UI actions:

- `DuplicateSopsInSeries.sql` defines an actual duplicate SOP as **same `sop_instance_uid`, different file IDs**.
- `Checking Duplicate Pixel Data By Series.sql` separately groups by `pixel_data_digest`, proving that duplicate SOP identity and duplicate pixel content are distinct concepts.
- `DuplicateSopResolution.pm` fetches duplicate SOP info, exposes comparison flows, and allows explicit keep-selection policies such as latest/earliest receipt.
  - Evidence:
    - `research/repos/posda-tools/posda/posdatools/queries/sql/DuplicateSopsInSeries.sql`
    - `research/repos/posda-tools/posda/posdatools/queries/sql/Checking Duplicate Pixel Data By Series.sql`
    - `research/repos/posda-tools/posda/posdatools/PosdaCuration/include/PosdaCuration/DuplicateSopResolution.pm`

### Why this matters for our design

This is stronger than merely “track duplicates.” It argues for **two explicit duplicate axes** from day one:

1. **identity duplicate** — same SOP Instance UID
2. **content duplicate** — same pixel digest (and potentially same whole-file digest)

And it argues that we should not overload `imported=true` to mean `accepted=true`.

A cleaner state model is:

- `received`
- `parsed`
- `validated`
- `quarantined | accepted`
- optional duplicate classification attached separately

That lets the platform ingest aggressively while still preserving a governed path for clinical or dataset curation decisions.

---

## 4. OHIF: derived objects break if referential metadata is not preserved

### What the source actually does

OHIF’s runtime behavior makes the dependency explicit:

- Overlay display sets such as SEG and RTSTRUCT look for `referencedDisplaySetInstanceUID` to find the base image set they overlay.
  - Evidence: `research/repos/ohif-viewers/extensions/cornerstone/src/services/ViewportService/CornerstoneViewportService.ts`
- Structured Report hydration builds a lookup keyed by `ReferencedSOPInstanceUID + frameNumber`, then derives touched series and studies from those referenced images.
  - Evidence: `research/repos/ohif-viewers/extensions/cornerstone-dicom-sr/src/utils/hydrateStructuredReport.ts`

### Why this matters for our design

If our ingestion layer only keeps “flat tags we happen to query today,” later support for SEG / RTSTRUCT / SR becomes fragile or expensive.

From day one, the ingestion record should preserve at least:

- `StudyInstanceUID`
- `SeriesInstanceUID`
- `SOPInstanceUID`
- `FrameOfReferenceUID`
- referenced SOP / series / study relationships
- frame numbers where relevant

The important product-level point is:

> **The viewer problem begins at ingestion time.**

If reference graphs are lost during ingestion, downstream viewers, labeling tools, and cohort builders all pay the price later.

---

## 5. Orthanc: a mature server keeps a fast indexed projection distinct from the full DICOM object

### What the source actually shows

Orthanc maintains a dedicated concept of **main DICOM tags** stored in the DB separately from the full instance payload:

- `MainDicomTags` are first-class enough to have their own registry, DB accessors, reconstruction paths, and change management.
- There are explicit flows to reconstruct them when configuration changes.
- Unit tests include `DicomUntilPixelData`, reinforcing the same header-before-pixel pattern seen elsewhere.
  - Evidence:
    - `research/repos/orthanc-src/OrthancServer/Sources/Database/MainDicomTagsRegistry.cpp`
    - `research/repos/orthanc-src/OrthancServer/Sources/ServerIndex.cpp`
    - `research/repos/orthanc-src/OrthancServer/UnitTestsSources/ServerIndexTests.cpp`
    - `research/repos/orthanc-src/NEWS`

### Why this matters for our design

This is a useful complement to Dicoogle:

- **canonical source** = immutable original DICOM bytes + full parsed metadata as needed
- **fast projection** = selected normalized fields optimized for common filters / joins / UI

This split matters because the query model will evolve. If we keep only one denormalized ingestion table, every new query need risks either migration pain or over-indexing everything too early.

---

# Consolidated design guidance for our non-PACS ingestion module

## Strongly supported by source evidence

1. **Use a staged ingestion pipeline** rather than one giant synchronous transaction.
2. **Persist immutable source bytes before derived work.**
3. **Make header-only parsing a first-class fast path.**
4. **Separate canonical ingest records from fast query projections.**
5. **Keep platform-specific identity mapping outside the low-level parser.**
6. **Model indexing / enrichment as jobs with reports and retries.**
7. **Treat duplicate identity and duplicate content as separate dimensions.**
8. **Preserve derived-object reference graphs from day one.**

## Still not fully proven and should remain explicit design choices

1. The exact best abstraction for our own Study / Series / Subject mapping layer.
2. Whether we need plugin-style extensibility immediately, or only a simpler internal interface first.
3. How much of Posda-style curation we need in v1 versus later.
4. Whether our first query projection should be relational, search-index based, or hybrid.

---

# Recommended next product decision

If we are designing the **10-star version** rather than the smallest parser that merely works, the product should not be framed as “upload DICOM and read tags.”

It should be framed as:

> **A trustworthy medical imaging intake layer for the data platform: byte-preserving, queryable, replayable, duplicate-aware, and ready for derived objects.**

That framing is important because it changes the architecture from “file parser” to “ingestion subsystem,” which is where the source evidence points.
