"""Health check system for DICOM ingestion services."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Any


class HealthStatus(str, Enum):
    """Overall health status."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"


@dataclass
class CheckResult:
    """Result of a single health check."""
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def healthy(cls, message: str = "OK", **details) -> "CheckResult":
        return cls(status=HealthStatus.HEALTHY, message=message, details=details)

    @classmethod
    def unhealthy(cls, message: str, **details) -> "CheckResult":
        return cls(status=HealthStatus.UNHEALTHY, message=message, details=details)

    @classmethod
    def degraded(cls, message: str, **details) -> "CheckResult":
        return cls(status=HealthStatus.DEGRADED, message=message, details=details)


@dataclass
class ServiceStatus:
    """Overall service health status."""
    service: str
    status: HealthStatus
    checks: Dict[str, CheckResult]
    timestamp: str


class HealthCheck:
    """Health check manager for a service."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        self._checks: Dict[str, Callable[[], CheckResult]] = {}

    def add_check(self, name: str, check_fn: Callable[[], CheckResult]) -> None:
        """Add a health check function."""
        self._checks[name] = check_fn

    def get_status(self) -> ServiceStatus:
        """Run all health checks and return overall status."""
        from datetime import datetime, timezone

        results: Dict[str, CheckResult] = {}
        overall = HealthStatus.HEALTHY

        for name, check_fn in self._checks.items():
            try:
                result = check_fn()
                results[name] = result

                # Overall is the worst of all checks
                if result.status == HealthStatus.UNHEALTHY:
                    overall = HealthStatus.UNHEALTHY
                elif result.status == HealthStatus.DEGRADED and overall == HealthStatus.HEALTHY:
                    overall = HealthStatus.DEGRADED
            except Exception as e:
                results[name] = CheckResult.unhealthy(f"Check failed: {str(e)}")
                overall = HealthStatus.UNHEALTHY

        return ServiceStatus(
            service=self.service_name,
            status=overall,
            checks=results,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def to_dict(self) -> Dict:
        """Convert status to dictionary for JSON serialization."""
        status = self.get_status()
        return {
            "service": status.service,
            "status": status.status.value,
            "timestamp": status.timestamp,
            "checks": {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "details": result.details
                }
                for name, result in status.checks.items()
            }
        }
