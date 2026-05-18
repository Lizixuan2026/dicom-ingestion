"""Integration tests for Batch 6 production readiness features."""

import pytest
from dicom_ingestion.observability.metrics import Counter, Histogram, MetricsRegistry
from dicom_ingestion.observability.collector import PipelineMetricsCollector, PipelineStage
from dicom_ingestion.observability.health import HealthCheck, CheckResult, HealthStatus
from dicom_ingestion.security.input_validator import InputValidator
from dicom_ingestion.security.audit_logger import AuditLogger, AuditAction
from dicom_ingestion.security.phi_filter import PhiFilter
from dicom_ingestion.ops.smoke_tests import SmokeTestSuite, SmokeTestResult


class TestBatch6Integration:
    """End-to-end tests for production readiness."""
    
    def test_observability_pipeline(self):
        """Test full observability pipeline."""
        registry = MetricsRegistry()
        collector = PipelineMetricsCollector(registry)
        
        collector.record_job_started("job_1")
        
        collector.record_stage_complete(
            item_id="item_1",
            stage=PipelineStage.SCAN,
            success=True,
            duration_ms=100
        )
        
        collector.record_stage_complete(
            item_id="item_1",
            stage=PipelineStage.PARSE,
            success=False,
            duration_ms=50,
            error_code="PARSE_ERROR"
        )
        
        output = collector.get_metrics_output()
        assert "dicom_ingestion_items_total" in output
        assert "dicom_ingestion_stage_duration_ms" in output
        assert "dicom_ingestion_errors_total" in output
    
    def test_security_pipeline(self, caplog):
        """Test security controls pipeline."""
        import logging
        
        validator = InputValidator()
        
        result = validator.validate_path("folder/file.dcm")
        assert result.is_valid
        
        result = validator.validate_path("../../../etc/passwd")
        assert not result.is_valid
        
        data = {"patient_name": "John Doe", "study_instance_uid": "1.2.3.4", "rows": 512}
        filtered = PhiFilter.filter_for_logging(data)
        assert filtered["patient_name"] == "[REDACTED-PHI]"
        assert filtered["study_instance_uid"] == "1.2.3.4"
        
        # Test audit logger using caplog
        with caplog.at_level(logging.INFO, logger="dicom_ingestion.audit"):
            audit_logger = AuditLogger()  # No file path, uses stream handler
            audit_logger.log_phi_access(
                action=AuditAction.READ,
                actor_id="test_user",
                resource_type="dicom_instance",
                resource_id="inst_1",
                phi_fields=["study_instance_uid"],
                success=True
            )
        
        # Verify audit log was captured
        assert "READ" in caplog.text
        assert "test_user" in caplog.text
    
    def test_health_and_smoke_checks(self):
        """Test health checks and smoke test framework."""
        health = HealthCheck("dicom_ingestion")
        health.add_check("db", lambda: CheckResult.healthy("OK"))
        
        status = health.get_status()
        assert status.status == HealthStatus.HEALTHY
        
        suite = SmokeTestSuite("dicom_ingestion")
        
        def passing_test():
            return SmokeTestResult.passed("OK")
        
        suite.add_test("always_passes", passing_test)
        result = suite.run()
        
        assert result.success
        assert result.tests["always_passes"].passed
    
    def test_end_to_end_production_readiness(self, tmp_path):
        """Complete production readiness verification."""
        registry = MetricsRegistry()
        counter = Counter("test_e2e", "End to end test counter")
        registry.register(counter)
        counter.inc()
        
        validator = InputValidator()
        assert validator.validate_uid("1.2.840.10008.1.2.1").is_valid
        
        data = {"patient_name": "Secret", "modality": "CT"}
        filtered = PhiFilter.filter_for_logging(data)
        assert filtered["patient_name"] == "[REDACTED-PHI]"
        assert filtered["modality"] == "CT"
        
        health = HealthCheck("test")
        health.add_check("test", lambda: CheckResult.healthy("OK"))
        assert health.get_status().status == HealthStatus.HEALTHY
        
        suite = SmokeTestSuite("test")
        suite.add_test("test", lambda: SmokeTestResult.passed("OK"))
        assert suite.run().success
