"""Deployment validation checks."""

from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class CheckResult:
    """Result of a deployment check."""
    check_name: str
    valid: bool
    message: str
    details: Optional[dict] = None


class MigrationCheck:
    """Verify database migrations are up to date."""
    
    def __init__(
        self,
        current_revision_fn: Callable[[], str],
        expected_revision_fn: Callable[[], str]
    ):
        self.current_revision_fn = current_revision_fn
        self.expected_revision_fn = expected_revision_fn
    
    def validate(self) -> CheckResult:
        """Check if migrations are current."""
        try:
            current = self.current_revision_fn()
            expected = self.expected_revision_fn()
            
            if current == expected:
                return CheckResult(
                    check_name="migration",
                    valid=True,
                    message=f"Database migrations up to date (revision: {current})"
                )
            else:
                return CheckResult(
                    check_name="migration",
                    valid=False,
                    message=f"Migration mismatch: current={current}, expected={expected}",
                    details={"current": current, "expected": expected}
                )
        except Exception as e:
            return CheckResult(
                check_name="migration",
                valid=False,
                message=f"Failed to check migrations: {str(e)}"
            )


class ConfigurationCheck:
    """Verify required configuration is present."""
    
    REQUIRED_CONFIGS = [
        "DATABASE_URL",
        "OBJECT_STORAGE_URL",
        "LOG_LEVEL",
    ]
    
    def __init__(self, get_config_fn: Callable[[str], Optional[str]]):
        self.get_config_fn = get_config_fn
    
    def validate(self) -> CheckResult:
        """Check all required config values are set."""
        missing = []
        for key in self.REQUIRED_CONFIGS:
            value = self.get_config_fn(key)
            if not value:
                missing.append(key)
        
        if missing:
            return CheckResult(
                check_name="configuration",
                valid=False,
                message=f"Missing required configuration: {', '.join(missing)}"
            )
        
        return CheckResult(
            check_name="configuration",
            valid=True,
            message="All required configuration values present"
        )


class DeploymentValidator:
    """Validates deployment readiness."""
    
    def __init__(self):
        self._checks: List[Callable[[], CheckResult]] = []
    
    def add_check(self, check: Callable[[], CheckResult]) -> None:
        """Add a validation check."""
        self._checks.append(check)
    
    def validate(self) -> List[CheckResult]:
        """Run all deployment checks."""
        results = []
        for check in self._checks:
            try:
                result = check()
                results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    check_name="unknown",
                    valid=False,
                    message=f"Check raised exception: {str(e)}"
                ))
        return results
    
    def is_valid(self) -> bool:
        """Check if all validations pass."""
        results = self.validate()
        return all(r.valid for r in results)
