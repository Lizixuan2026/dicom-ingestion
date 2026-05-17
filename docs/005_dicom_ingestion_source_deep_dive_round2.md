# DICOM Ingestion Source Deep Dive — Round 2

This round answers three narrower questions that still had power to change the architecture:

1. What exactly does `dcm4che` prove about metadata-only parsing and private tags?
2. What does Orthanc really persist on the write path, and where is the split between canonical bytes and query projection?
3. Does Kaapana only look like a workflow system, or does it already treat derived objects as a distinct processing branch?

---

## 1. dcm4che: metadata-only parsing and private tags are both explicit APIs

### 1.1 Metadata-only parsing is not a convention. It is an API.

`DicomInputStream` contains both:

- `readDataset()`
- `readDatasetUntilPixelData()`

`readDatasetUntilPixelData()` is implemented as:

```java
return readDataset(o -> o.tag == Tag.PixelData);
```

and the generic parser loop in `readAttributes(...)` stops when the predicate returns true.

**Evidence**

- `research/repos/dcm4che/dcm4che-core/src/main/java/org/dcm4che3/io/DicomInputStream.java`
  - `readDatasetUntilPixelData()`
  - `readDataset(Predicate<DicomInputStream> stopPredicate)`
  - `readAttributes(..., Predicate<DicomInputStream> stopPredicate)`

### Why this matters

Earlier, XNAT showed that production code uses stop-before-pixel parsing. `dcm4che` now makes the point stronger:

> **The parser library itself treats “read metadata without pixel payload” as a first-class operation.**

For our module, `header_only` should not be an optimization hidden behind the scenes. It should be an explicit mode in the ingestion contract.

---

### 1.2 Private tags are keyed by private creator, not just by numeric tag

`ElementDictionary.getElementDictionary(privateCreator)` resolves a dictionary by the private creator string, using `ServiceLoader<ElementDictionary>` to load vendor-specific dictionaries. `Attributes` APIs then consistently accept `privateCreator` alongside the numeric tag when reading values.

**Evidence**

- `research/repos/dcm4che/dcm4che-core/src/main/java/org/dcm4che3/data/ElementDictionary.java`
- `research/repos/dcm4che/dcm4che-core/src/main/java/org/dcm4che3/data/Attributes.java`
- `research/repos/dcm4che/dcm4che-dict-priv/src/main/resources/META-INF/services/org.dcm4che3.data.ElementDictionary`

### Why this matters

This sharpens the earlier private-tag conclusion. A private element is not safely identified by `(group, element)` alone. You need at least:

```text
(private_creator, private_tag, vr, raw_value)
```

And interpretation is a separate layer:

```text
raw retention
  -> creator-aware dictionary lookup
  -> optional platform mapping
```

That is the real architecture. A flat `private_tags JSONB` blob is acceptable for retention, but not enough as the entire model if vendor semantics matter later.

---

## 2. Orthanc: the write path proves a three-layer persistence model

### 2.1 The actual write chain

Orthanc’s store flow is not vague. In `ServerContext::StoreAfterTranscoding(...)` it does all of this:

1. Calculates `pixelDataOffset` from the incoming bytes.
2. Builds a DICOM `summary` from the instance.
3. Writes the **full DICOM file** attachment.
4. Optionally writes a separate **DicomUntilPixelData** attachment when efficient range reads are unavailable or compression is enabled.
5. Calls `index_.Store(...)` with:
   - summary
   - attachments
   - metadata
   - origin
   - transfer syntax
   - pixel-data offset metadata
6. `ServerIndex::Store(...)` forwards into database operations for indexed persistence.

**Evidence**

- `research/repos/orthanc-src/OrthancServer/Sources/ServerContext.cpp`
- `research/repos/orthanc-src/OrthancServer/Sources/ServerIndex.cpp`

### 2.2 `DicomInstanceToStore` is the bridge object between bytes and parsed view

`DicomInstanceToStore` can be constructed from:

- raw buffer
- parsed DICOM file
- `DcmDataset`

It lazily exposes both:

- raw bytes via `GetBufferData()` / `GetBufferSize()`
- parsed structure via `GetParsedDicomFile()` / `GetSummary()` / `GetDicomAsJson()`

**Evidence**

- `research/repos/orthanc-src/OrthancServer/Sources/DicomInstanceToStore.cpp`

### 2.3 What this proves

The useful architectural pattern is not just “store bytes and metadata.” It is more specific:

```text
canonical bytes
+ metadata-only byte prefix / fast-access attachment
+ normalized indexed summary
```

Orthanc also has explicit `MainDicomTags` reconstruction machinery, so the indexed projection is treated as **rebuildable derived state**, not the canonical truth.

### Why this matters for our module

This changes the quality bar for our design. A 10-star ingestion layer should not merely save:

```text
raw_file + parsed_json
```

It should deliberately separate:

1. **source of truth**: immutable original object bytes
2. **fast metadata materialization**: enough to answer common queries quickly
3. **rebuildable projections**: indexes and denormalized query views

The interesting nuance is `DicomUntilPixelData`: Orthanc sometimes stores the metadata-only prefix as its own attachment because reading that range repeatedly from compressed storage is expensive. We may not need the same exact mechanism in v1, but it proves the access pattern matters enough in mature systems to deserve its own storage optimization.

---

## 3. Kaapana: derived objects are not a postscript. They create a different DAG.

### 3.1 The simple DAG

`dag_collect_metadata.py` is a straight pipeline:

```text
GetInput
  -> LocalDcmAnonymizerOperator(single_slice=True)
  -> LocalDcm2JsonOperator
  -> LocalConcatJsonOperator
  -> MinioOperator
  -> LocalWorkflowCleanerOperator
```

### 3.2 The advanced DAG

`dag_advanced_collect_metadata.py` branches after base metadata extraction:

```text
COMMON
GetInput -> anonymizer -> dcm2json

IMAGE BRANCH
GetInput -> dcm2nifti_ct
GetInput + metadata -> extract_img_intensities

SEG BRANCH
metadata -> dcm2nifti_seg
GetInput -> dcm2nifti_ct -> extract_seg_metadata
seg -> extract_seg_metadata -> cca -> concat_metadata

MERGE
extract_img_intensities + concat_metadata -> merge_branches -> minio -> clean
```

**Evidence**

- `research/repos/kaapana/data-processing/kaapana-plugin/extension/docker/files/dags/dag_collect_metadata.py`
- `research/repos/kaapana/data-processing/processing-pipelines/advanced-collect-metadata/extension/docker/files/dag_advanced_collect_metadata.py`
- `research/repos/kaapana/data-processing/processing-pipelines/advanced-collect-metadata/extension/docker/files/advanced_collect_metadata/LocalExtractImgIntensitiesOperator.py`
- `research/repos/kaapana/data-processing/processing-pipelines/advanced-collect-metadata/extension/docker/files/advanced_collect_metadata/LocalExtractSegMetadataOperator.py`
- `research/repos/kaapana/data-processing/processing-pipelines/advanced-collect-metadata/extension/docker/files/advanced_collect_metadata/LocalMergeBranchesOperator.py`

### 3.3 What the branch operators prove

The branches are semantically different, not cosmetic:

- `LocalExtractImgIntensitiesOperator`
  - only accepts CT/MR samples
  - computes intensity histograms from image pixels
- `LocalExtractSegMetadataOperator`
  - only accepts SEG samples
  - uses the corresponding CT/MR image spacing to compute voxel volume and per-class segmentation volume
- `LocalMergeBranchesOperator`
  - explicitly merges outputs from distinct branches

### Why this matters

This is stronger than the generic statement “support derived objects later.”

It says:

> **If your product intends to ingest both base images and derived objects, the pipeline graph itself eventually diverges.**

For our architecture, that means v1 does not need every derived-object computation, but it should avoid a design that assumes one linear image-only pipeline forever.

A better early boundary is:

```text
common intake stage
  -> object classification
  -> branch-specific enrichment
  -> shared persistence / indexing contracts
```

That leaves room for SEG, RTSTRUCT, SR, and future non-image artifacts without rewriting the spine later.

---

# Round 2 conclusions

## Conclusions now strong enough to drive architecture

1. **Header-only parse must be an explicit ingestion mode**, not an incidental optimization.
2. **Private tags require creator-aware identity**, not numeric-tag-only storage.
3. **Canonical bytes and query projections should be separate layers.**
4. **Metadata projections should be rebuildable derived state.**
5. **Derived objects justify branch-capable workflows**, even if v1 only implements the common trunk plus minimal classification.

## Conclusions still not fully settled

1. Whether we should physically persist a `bytes-until-pixel-data` derivative like Orthanc in v1.
2. Which exact private-tag interpretation set matters for our first customer / dataset cohort.
3. Whether our branching mechanism should be a general workflow engine, a typed internal dispatcher, or a simpler staged job runner first.

## Net effect on our product framing

The design target should move from:

> “A DICOM parser inside the platform”

further toward:

> **“A replayable imaging intake system with canonical storage, fast projections, and branchable enrichment.”**

That is the point where the module stops being a utility and starts becoming infrastructure.
