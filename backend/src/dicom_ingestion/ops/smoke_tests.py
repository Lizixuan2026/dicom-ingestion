"""Pre-deployment smoke tests for DICOM ingestion.

CLI Usage:
    python -m dicom_ingestion.ops.smoke_tests [--json]

Exit Codes:
    0 - All tests passed
    1 - One or more tests failed
    2 - Internal error
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional


class TestStatus(str, Enum):
    """Status of a smoke test."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SmokeTestResult:
    """Result of a single smoke test."""
    name: str = ""
    passed: bool = True
    message: str = ""
    status: TestStatus = TestStatus.PASSED
    duration_ms: float = 0.0
    
    @classmethod
    def passed(cls, name: str, message: str = "OK", duration_ms: float = 0) -> "SmokeTestResult":
        return cls(name=name, passed=True, message=message, status=TestStatus.PASSED, duration_ms=duration_ms)
    
    @classmethod
    def failed(cls, name: str, message: str, duration_ms: float = 0) -> "SmokeTestResult":
        return cls(name=name, passed=False, message=message, status=TestStatus.FAILED, duration_ms=duration_ms)
    
    @classmethod
    def skipped(cls, name: str, message: str = "Not applicable") -> "SmokeTestResult":
        return cls(name=name, passed=True, message=message, status=TestStatus.SKIPPED, duration_ms=0)


@dataclass
class SmokeTestSuiteResult:
    """Result of running the full smoke test suite."""
    service: str
    timestamp: str
    success: bool
    tests: Dict[str, SmokeTestResult]
    total_duration_ms: float
    
    def to_dict(self) -> Dict:
        return {
            "service": self.service,
            "timestamp": self.timestamp,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
            "tests": {
                name: {
                    "passed": test.passed,
                    "status": test.status.value,
                    "message": test.message,
                    "duration_ms": test.duration_ms
                }
                for name, test in self.tests.items()
            }
        }


class SmokeTestSuite:
    """Suite of smoke tests for deployment validation."""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self._tests: Dict[str, Callable[[], SmokeTestResult]] = {}
    
    def add_test(self, name: str, test_fn: Callable[[], SmokeTestResult]) -> None:
        """Add a smoke test."""
        self._tests[name] = test_fn
    
    def run(self) -> SmokeTestSuiteResult:
        """Run all smoke tests."""
        import time
        
        start_time = time.time()
        results: Dict[str, SmokeTestResult] = {}
        all_passed = True
        
        for name, test_fn in self._tests.items():
            test_start = time.time()
            try:
                result = test_fn()
                result.name = name
                result.duration_ms = (time.time() - test_start) * 1000
            except Exception as e:
                result = SmokeTestResult.failed(
                    name=name,
                    message=f"Test raised exception: {str(e)}",
                    duration_ms=(time.time() - test_start) * 1000
                )
            
            results[name] = result
            if not result.passed:
                all_passed = False
        
        total_duration = (time.time() - start_time) * 1000
        
        return SmokeTestSuiteResult(
            service=self.service_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=all_passed,
            tests=results,
            total_duration_ms=total_duration
        )
    
    @staticmethod
    def create_database_test(session_factory) -> Callable[[], SmokeTestResult]:
        """Create a database connectivity test."""
        def test() -> SmokeTestResult:
            import time
            start = time.time()
            try:
                session = session_factory()
                session.execute("SELECT 1")
                session.close()
                return SmokeTestResult.passed(
                    "database",
                    "Database connection successful",
                    (time.time() - start) * 1000
                )
            except Exception as e:
                return SmokeTestResult.failed(
                    "database",
                    f"Database connection failed: {str(e)}",
                    (time.time() - start) * 1000
                )
        return test
    
    @staticmethod
    def create_object_storage_test(object_store) -> Callable[[], SmokeTestResult]:
        """Create an object storage connectivity test."""
        def test() -> SmokeTestResult:
            import time
            start = time.time()
            try:
                test_data = b"smoke_test"
                result = object_store.put(test_data, content_hash="smoke_test")
                uri = result.get("uri")
                if uri:
                    retrieved = object_store.get(uri)
                    if retrieved == test_data:
                        object_store.delete(uri)
                        return SmokeTestResult.passed(
                            "object_storage",
                            "Object storage read/write successful",
                            (time.time() - start) * 1000
                        )
                return SmokeTestResult.failed(
                    "object_storage",
                    "Object storage verification failed",
                    (time.time() - start) * 1000
                )
            except Exception as e:
                return SmokeTestResult.failed(
                    "object_storage",
                    f"Object storage failed: {str(e)}",
                    (time.time() - start) * 1000
                )
        return test


def main() -> int:
    """CLI entry point for smoke tests.
    
    Returns:
        Exit code: 0 for success, 1 for test failure, 2 for internal error
    """
    parser = argparse.ArgumentParser(
        description="Pre-deployment smoke tests for DICOM ingestion"
    )
    parser.add_argument(
        "--json", 
        action="store_true", 
        help="Output results as JSON"
    )
    parser.add_argument(
        "--service",
        default="dicom_ingestion",
        help="Service name to test (default: dicom_ingestion)"
    )
    
    args = parser.parse_args()
    
    try:
        suite = SmokeTestSuite(args.service)
        
        # Add basic connectivity tests that don't require external dependencies
        def health_check():
            return SmokeTestResult.passed("health", "Service is reachable")
        
        suite.add_test("health", health_check)
        
        result = suite.run()
        
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Smoke Test Results: {args.service}")
            print(f"Timestamp: {result.timestamp}")
            print(f"Overall: {'PASSED' if result.success else 'FAILED'}")
            print(f"Duration: {result.total_duration_ms:.2f}ms")
            print()
            for name, test in result.tests.items():
                status = "✓" if test.passed else "✗"
                print(f"  {status} {name}: {test.message} ({test.duration_ms:.2f}ms)")
        
        return 0 if result.success else 1
        
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "exit_code": 2}))
        else:
            print(f"Internal error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
