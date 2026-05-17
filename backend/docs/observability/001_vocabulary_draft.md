# DICOM Ingestion Observability Vocabulary Draft

## Stages
- `receive`: Initial byte intake.
- `scan`: Enumeration and validation of package safety.
- `parse`: DICOM header extraction.
- `store`: Raw byte durable persistence.
- `persist_metadata`: Writing headers to `dicom_instances` / `dicom_instance_observations`.
- `validate`: Invariant checking on the metadata (e.g., duplicate detection).
- `bind`: Associating the instance to the correct study/series.
- `index`: Triggering projection rebuilds and search indexing.

## Event Names
- `ingestion.started`
- `ingestion.completed`
- `ingestion.failed`
- `item.scanned`
- `item.rejected_unsafe`
- `item.parsed`
- `item.parse_failed`
- `item.stored`
- `item.metadata_persisted`
- `item.duplicate_detected`
- `item.reference_edge_created`
- `item.binding_resolved`

## Structured Keys
- `job_id`: ID of the `dicom_ingestion_jobs`
- `actor_id`: Initiator of the request
- `item_id`: ID of the `dicom_ingestion_items`
- `series_ingestion_attempt_id`: ID of the `dicom_series_ingestion_attempts`
- `item_fingerprint`: Unique hash of the item
- `study_instance_uid`
- `series_instance_uid`
- `sop_instance_uid`
- `stage`: Name of the pipeline stage
- `error_code`

## PHI Exclusions
Do **NOT** log the following under any circumstances:
- `patient_name`
- `patient_id`
- Raw DICOM tag values unless explicitly allowlisted
