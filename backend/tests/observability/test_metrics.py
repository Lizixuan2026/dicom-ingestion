import pytest
from dicom_ingestion.observability.metrics import Counter, Histogram, MetricsRegistry


class TestCounter:
    def test_counter_increment(self):
        counter = Counter("test_counter", "A test counter")
        counter.inc()
        assert counter.get_value() == 1
        counter.inc(5)
        assert counter.get_value() == 6

    def test_counter_labels(self):
        counter = Counter("test_labeled_counter", "Counter with labels", labels=["stage"])
        counter.inc(labels={"stage": "scan"})
        counter.inc(labels={"stage": "parse"})
        assert counter.get_value({"stage": "scan"}) == 1
        assert counter.get_value({"stage": "parse"}) == 1


class TestHistogram:
    def test_histogram_observe(self):
        hist = Histogram("test_histogram", "A test histogram", buckets=[0.1, 0.5, 1.0, 5.0])
        hist.observe(0.3)
        hist.observe(1.5)
        hist.observe(0.05)
        
        assert hist.sum == 1.85
        assert hist.count == 3


class TestMetricsRegistry:
    def test_register_and_collect(self):
        registry = MetricsRegistry()
        counter = Counter("requests_total", "Total requests")
        registry.register(counter)
        
        counter.inc()
        output = registry.output_prometheus_format()
        
        assert "requests_total" in output
        assert "1" in output
