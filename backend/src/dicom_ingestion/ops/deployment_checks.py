"""Deployment validation checks.

CLI Usage:
    python -m dicom_ingestion.ops.deployment_checks [--json]

Exit Codes:
    0 - All checks passed
    1 - One or more checks failed
    2 - Internal error
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class CheckResult:
    """Result of a deployment check."""
    check_name: str
    valid: bool
    message: str
    details: Optional[dict] = None
    
    def to_dict(self) -> dict:
        return {
            "check_name": self.check_name,
            "valid": self.valid,
            "message": self.message,
            "details": self.details
        }


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


def main() -> int:
    """CLI entry point for deployment checks.
    
    Returns:
        Exit code: 0 for success, 1 for check failure, 2 for internal error
    """
    parser = argparse.ArgumentParser(
        description="Deployment validation checks for DICOM ingestion"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Check configuration variables"
    )
    
    args = parser.parse_args()
    
    try:
        validator = DeploymentValidator()
        
        # Add configuration check if requested
        if args.check_config:
            def get_env_config(key: str) -> Optional[str]:
                return os.environ.get(key)
            
            config_check = ConfigurationCheck(get_env_config)
            validator.add_check(lambda: config_check.validate())
        
        # Always add a basic health check
        def basic_check():
            return CheckResult(
                check_name="deployment",
                valid=True,
                message="Deployment validator is operational"
            )
        validator.add_check(basic_check)
        
        results = validator.validate()
        is_valid = all(r.valid for r in results)
        
        if args.json:
            output = {
                "valid": is_valid,
                "checks": [r.to_dict() for r in results]
            }
            print(json.dumps(output, indent=2))
        else:
            print("Deployment Validation Results")
            print(f"Overall: {'PASSED' if is_valid else 'FAILED'}")
            print()
            for result in results:
                status = "✓" if result.valid else "✗"
                print(f"  {status} {result.check_name}: {result.message}")
        
        return 0 if is_valid else 1
        
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "exit_code": 2}))
        else:
            print(f"Internal error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
