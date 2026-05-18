"""Audit logging for PHI-touching operations."""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class AuditAction(str, Enum):
    """Audit actions for PHI operations."""
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXPORT = "EXPORT"
    REPLAY = "REPLAY"
    RETRY = "RETRY"


@dataclass
class AuditEvent:
    """Audit event for PHI operations."""
    timestamp: str
    action: str
    actor_id: str
    resource_type: str
    resource_id: str
    phi_accessed: bool
    phi_fields: List[str]
    success: bool
    error_code: Optional[str] = None
    correlation_id: Optional[str] = None
    additional_data: Dict = field(default_factory=dict)


class AuditLogger:
    """Audit logger for PHI-touching operations."""
    
    def __init__(self, log_path: Optional[str] = None):
        self._logger = logging.getLogger("dicom_ingestion.audit")
        self._logger.setLevel(logging.INFO)
        
        if not self._logger.handlers and log_path:
            handler = logging.FileHandler(log_path)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
    
    def _get_timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()
    
    def _get_correlation_id(self) -> Optional[str]:
        try:
            from ..observability.logging_config import get_correlation_id
            return get_correlation_id()
        except ImportError:
            return None
    
    def log_phi_access(
        self,
        action: AuditAction,
        actor_id: str,
        resource_type: str,
        resource_id: str,
        phi_fields: List[str],
        success: bool,
        error_code: Optional[str] = None,
        **additional_data
    ) -> None:
        """Log a PHI access event."""
        event = AuditEvent(
            timestamp=self._get_timestamp(),
            action=action.value,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            phi_accessed=len(phi_fields) > 0,
            phi_fields=phi_fields,
            success=success,
            error_code=error_code,
            correlation_id=self._get_correlation_id(),
            additional_data=additional_data
        )
        
        self._logger.info(json.dumps(asdict(event), default=str))
    
    def log_ingestion_start(self, job_id: str, actor_id: str, item_count: int) -> None:
        """Log when an ingestion job starts."""
        self.log_phi_access(
            action=AuditAction.CREATE,
            actor_id=actor_id,
            resource_type="ingestion_job",
            resource_id=job_id,
            phi_fields=[],
            success=True,
            item_count=item_count
        )
    
    def log_replay(self, item_id: str, actor_id: str, stage: str, success: bool) -> None:
        """Log a replay operation."""
        self.log_phi_access(
            action=AuditAction.REPLAY,
            actor_id=actor_id,
            resource_type="ingestion_item",
            resource_id=item_id,
            phi_fields=["dicom_metadata"],
            success=success,
            stage=stage
        )
    
    def log_binding_resolution(
        self,
        item_id: str,
        actor_id: str,
        study_uid: str,
        series_uid: str,
        success: bool
    ) -> None:
        """Log when binding policy resolves associations."""
        self.log_phi_access(
            action=AuditAction.READ,
            actor_id=actor_id,
            resource_type="ingestion_item",
            resource_id=item_id,
            phi_fields=["study_instance_uid", "series_instance_uid"],
            success=success,
            study_uid=study_uid,
            series_uid=series_uid
        )
