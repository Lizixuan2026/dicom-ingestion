import pytest
from dicom_ingestion.ops.smoke_tests import SmokeTestSuite, SmokeTestResult, TestStatus


class TestSmokeTestSuite:
    def test_successful_smoke_test(self):
        suite = SmokeTestSuite("test_service")
        
        def passing_check():
            return SmokeTestResult.passed("OK")
        
        suite.add_test("db_connection", passing_check)
        result = suite.run()
        
        assert result.success
        assert result.tests["db_connection"].passed

    def test_failing_smoke_test(self):
        suite = SmokeTestSuite("test_service")
        
        def failing_check():
            return SmokeTestResult.failed("DB down")
        
        suite.add_test("db_connection", failing_check)
        result = suite.run()
        
        assert not result.success
        assert not result.tests["db_connection"].passed
