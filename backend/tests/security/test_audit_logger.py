import json
import pytest
from datetime import datetime
from dicom_ingestion.security.audit_logger import AuditLogger, AuditAction


class TestAuditLogger:
    def test_log_phi_access(self, tmp_path):
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))
        
        logger.log_phi_access(
            action=AuditAction.READ,
            actor_id="user_123",
            resource_type="dicom_instance",
            resource_id="instance_456",
            phi_fields=["patient_name", "patient_id"],
            success=True
        )
        
        with open(log_file) as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["action"] == "READ"
        assert entry["actor_id"] == "user_123"
        assert entry["resource_type"] == "dicom_instance"
        assert "timestamp" in entry
        assert entry["phi_accessed"] == True
