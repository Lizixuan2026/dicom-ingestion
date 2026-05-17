"""
Item Repository — application-layer boundary for `dicom_ingestion_items`.

DB allows `series_ingestion_attempt_id = NULL`.
This layer enforces: accepted DICOM items must have `series_ingestion_attempt_id` set.
"""
import sqlalchemy as sa
from sqlalchemy.orm import Session


ITEMS_TABLE = sa.Table(
    "dicom_ingestion_items",
    sa.MetaData(),
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("terminal_outcome", sa.Text),
    sa.Column("series_ingestion_attempt_id", sa.BigInteger),
)


class ItemRepository:
    def __init__(self, session: Session):
        self._session = session

    def mark_as_accepted(self, item_id: int, attempt_id: int) -> None:
        """
        Marks an item as accepted and binds it to a series ingestion attempt.
        Raises ValueError if attempt_id is None, as accepted DICOM items must
        always reference a valid series_ingestion_attempt_id.
        """
        if attempt_id is None:
            raise ValueError(
                f"Accepted DICOM item {item_id} must have a series_ingestion_attempt_id. "
                "Non-DICOM items use mark_as_rejected() instead."
            )
        self._session.execute(
            sa.text(
                "UPDATE dicom_ingestion_items "
                "SET terminal_outcome = 'accepted', series_ingestion_attempt_id = :attempt_id "
                "WHERE id = :item_id"
            ),
            {"item_id": item_id, "attempt_id": attempt_id},
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
