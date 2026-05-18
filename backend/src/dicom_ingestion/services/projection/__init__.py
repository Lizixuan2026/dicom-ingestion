"""Projection services for DICOM ingestion.

This module provides services for building and querying read models (projections)
from the source-of-truth canonical data.
"""
from dicom_ingestion.services.projection.projection_service import (
    ProjectionService,
    ProjectionBuildResult,
    ProjectionQueryResult,
    ProjectionRebuildRequest,
)

__all__ = [
    "ProjectionService",
    "ProjectionBuildResult",
    "ProjectionQueryResult",
    "ProjectionRebuildRequest",
]
