import pytest
from dicom_ingestion.observability.collector import PipelineMetricsCollector, PipelineStage
from dicom_ingestion.observability.metrics import MetricsRegistry


class TestPipelineMetricsCollector:
    def test_record_stage_completion(self):
        registry = MetricsRegistry()
        collector = PipelineMetricsCollector(registry)

        collector.record_stage_start("item_1", PipelineStage.SCAN)
        collector.record_stage_complete("item_1", PipelineStage.SCAN, success=True, duration_ms=100)

        # Check counter was incremented
        counter = registry.get("dicom_ingestion_items_total")
        assert counter is not None
        assert counter.get_value({"stage": "scan", "status": "success"}) == 1

    def test_record_stage_failure(self):
        registry = MetricsRegistry()
        collector = PipelineMetricsCollector(registry)

        collector.record_stage_start("item_1", PipelineStage.SCAN)
        collector.record_stage_complete("item_1", PipelineStage.SCAN, success=False, duration_ms=50, error_code="PARSE_ERROR")

        counter = registry.get("dicom_ingestion_items_total")
        assert counter.get_value({"stage": "scan", "status": "failed"}) == 1

    def test_duration_histogram(self):
        registry = MetricsRegistry()
        collector = PipelineMetricsCollector(registry)

        collector.record_stage_complete("item_1", PipelineStage.PARSE, success=True, duration_ms=250)

        hist = registry.get("dicom_ingestion_stage_duration_ms")
        assert hist is not None
        assert hist.count == 1
        assert hist.sum == 250.0
