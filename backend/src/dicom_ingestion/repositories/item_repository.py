"""
Item Repository — application-layer boundary for `dicom_ingestion_items`.

DB allows `series_ingestion_attempt_id = NULL`.
This layer enforces:
  - Accepted DICOM items must have `series_ingestion_attempt_id` set (not None).
  - The attempt must belong to the *same* `ingestion_job_id` as the item.
    This is also enforced at DB level via a composite FK, but the repository
    guard provides an early, descriptive failure with a clear error message.
"""
import sqlalchemy as sa
from sqlalchemy.orm import Session


class ItemRepository:
    def __init__(self, session: Session):
        self._session = session

    def mark_as_accepted(self, item_id: int, attempt_id: int) -> None:
        """
        Marks an item as accepted and binds it to a series ingestion attempt.

        Raises ValueError if:
        - attempt_id is None (non-DICOM items must use mark_as_rejected instead)
        - attempt_id belongs to a different ingestion_job_id than the item
        - item_id does not exist
        """
        if attempt_id is None:
            raise ValueError(
                f"Accepted DICOM item {item_id} must have a series_ingestion_attempt_id. "
                "Non-DICOM items use mark_as_rejected() instead."
            )

        result = self._session.execute(
            sa.text("""
                UPDATE dicom_ingestion_items AS i
                SET terminal_outcome = 'accepted',
                    series_ingestion_attempt_id = :attempt_id
                FROM dicom_series_ingestion_attempts AS a
                WHERE i.id = :item_id
                  AND a.id = :attempt_id
                  AND i.ingestion_job_id = a.ingestion_job_id
            """),
            {"item_id": item_id, "attempt_id": attempt_id},
        )

        if result.rowcount != 1:
            raise ValueError(
                f"Cannot accept item {item_id}: attempt {attempt_id} either does not exist "
                "or belongs to a different ingestion job. Cross-job binding is not permitted."
            )

    def mark_as_rejected(self, item_id: int, reason: str) -> None:
        """
        Marks a non-DICOM or scan-rejected item as rejected.
        `series_ingestion_attempt_id` intentionally remains NULL.
        """
        self._session.execute(
            sa.text(
                "UPDATE dicom_ingestion_items "
                "SET terminal_outcome = 'rejected', error_code = :reason "
                "WHERE id = :item_id"
            ),
            {"item_id": item_id, "reason": reason},
        )
