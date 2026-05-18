import json
import logging
import pytest
from dicom_ingestion.observability.logging_config import StructuredLogFormatter, CorrelationIdFilter
from dicom_ingestion.observability.logging_config import set_correlation_id, get_correlation_id, set_job_context, get_job_context


class TestStructuredLogFormatter:
    def test_basic_format(self):
        formatter = StructuredLogFormatter()
        
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.correlation_id = "abc-123"
        record.job_id = "job-456"
        
        output = formatter.format(record)
        parsed = json.loads(output)
        
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert parsed["correlation_id"] == "abc-123"
        assert parsed["job_id"] == "job-456"
        assert "timestamp" in parsed


class TestCorrelationContext:
    def test_set_and_get_correlation_id(self):
        set_correlation_id("test-corr-123")
        assert get_correlation_id() == "test-corr-123"
    
    def test_set_and_get_job_context(self):
        set_job_context(job_id="job-1", item_id="item-2")
        context = get_job_context()
        assert context["job_id"] == "job-1"
        assert context["item_id"] == "item-2"
