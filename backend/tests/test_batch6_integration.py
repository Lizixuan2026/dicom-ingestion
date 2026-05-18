"""Integration tests for Batch 6 production readiness features."""

import json
from pathlib import Path

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


class TestBatch6Artifacts:
    """Test operator-facing artifacts (dashboard, runbooks)."""
    
    def test_dashboard_json_exists(self):
        """Verify dashboard JSON file exists and is valid."""
        dashboard_path = Path(__file__).parent.parent / "dashboards" / "ingestion_dashboard.json"
        assert dashboard_path.exists(), "Dashboard JSON file should exist"
        
        with open(dashboard_path) as f:
            dashboard = json.load(f)
        
        assert "dashboard" in dashboard
        assert "title" in dashboard["dashboard"]
        assert "panels" in dashboard["dashboard"]
        assert len(dashboard["dashboard"]["panels"]) > 0
    
    def test_dashboard_has_key_panels(self):
        """Verify dashboard has key operational panels."""
        dashboard_path = Path(__file__).parent.parent / "dashboards" / "ingestion_dashboard.json"
        
        with open(dashboard_path) as f:
            dashboard = json.load(f)
        
        panels = dashboard["dashboard"]["panels"]
        panel_titles = [p.get("title", "").lower() for p in panels]
        
        # Check for critical operational panels
        assert any("ingestion" in t for t in panel_titles), "Should have ingestion rate panel"
        assert any("error" in t for t in panel_titles), "Should have error rate panel"
        assert any("duration" in t or "latency" in t for t in panel_titles), "Should have duration panel"
    
    def test_deployment_runbook_exists(self):
        """Verify deployment runbook exists and has key sections."""
        runbook_path = Path(__file__).parent.parent / "docs" / "runbooks" / "deployment.md"
        assert runbook_path.exists(), "Deployment runbook should exist"
        
        content = runbook_path.read_text()
        
        # Check for key sections per Batch6 gate requirements
        assert "Pre-Deployment Checklist" in content or "pre-deployment" in content.lower()
        assert "Rollback" in content or "rollback" in content.lower()
        assert "Post-Deployment" in content or "post-deployment" in content.lower()
        assert "Troubleshooting" in content or "troubleshooting" in content.lower()
    
    def test_incident_response_runbook_exists(self):
        """Verify incident response runbook exists and has key sections."""
        runbook_path = Path(__file__).parent.parent / "docs" / "runbooks" / "incident_response.md"
        assert runbook_path.exists(), "Incident response runbook should exist"
        
        content = runbook_path.read_text()
        
        # Check for key sections per Batch6 gate requirements
        assert "Severity" in content or "severity" in content.lower()
        assert "Escalation" in content or "escalation" in content.lower()
        assert "Post-Incident" in content or "post-incident" in content.lower() or "review" in content.lower()
    
    def test_compliance_doc_exists(self):
        """Verify compliance documentation exists."""
        compliance_path = Path(__file__).parent.parent / "docs" / "security" / "compliance.md"
        assert compliance_path.exists(), "Compliance documentation should exist"
        
        content = compliance_path.read_text()
        
        # Check for key compliance topics
        assert "HIPAA" in content or "hipaa" in content.lower()
        assert "PHI" in content
        assert "Audit" in content or "audit" in content.lower()
    
    def test_runbook_commands_executable_in_docs(self):
        """Verify runbook commands are documented and match CLI capabilities."""
        deployment_path = Path(__file__).parent.parent / "docs" / "runbooks" / "deployment.md"
        content = deployment_path.read_text()
        
        # Check that CLI commands are documented
        assert "python -m dicom_ingestion.ops.smoke_tests" in content
        assert "python -m dicom_ingestion.ops.deployment_checks" in content
        assert "--json" in content or "JSON" in content
