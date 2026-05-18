import pytest
from dicom_ingestion.observability.health import HealthCheck, HealthStatus, CheckResult


class TestHealthCheck:
    def test_basic_health_check(self):
        check = HealthCheck("test_service")
        check.add_check("database", lambda: CheckResult.healthy("DB connected"))
        
        status = check.get_status()
        assert status.status == HealthStatus.HEALTHY
        assert status.checks["database"].status == HealthStatus.HEALTHY

    def test_unhealthy_check(self):
        check = HealthCheck("test_service")
        check.add_check("database", lambda: CheckResult.unhealthy("DB down"))
        
        status = check.get_status()
        assert status.status == HealthStatus.UNHEALTHY
        assert status.checks["database"].status == HealthStatus.UNHEALTHY

    def test_mixed_health(self):
        check = HealthCheck("test_service")
        check.add_check("db", lambda: CheckResult.healthy("OK"))
        check.add_check("cache", lambda: CheckResult.unhealthy("Cache down"))
        
        status = check.get_status()
        assert status.status == HealthStatus.UNHEALTHY  # One failing = unhealthy
