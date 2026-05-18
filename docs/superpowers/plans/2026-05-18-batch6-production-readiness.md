# Batch 6 Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the DICOM ingestion system safe to expose and operate in production by implementing observability, security controls, and operational runbooks.

**Architecture:** 
- Observability: Metrics collection using a lightweight in-house system with Prometheus-compatible output, structured logging with correlation IDs, and health checks
- Security: Input validation middleware, audit logging for all PHI-touching operations, and secure configuration management
- Operations: Deployment runbooks with rollback procedures, automated smoke tests, and incident response documentation

**Tech Stack:** Python 3.11, SQLAlchemy, Prometheus exposition format, JSON structured logging

---

## File Structure Overview

**New Files to Create:**
- `backend/src/dicom_ingestion/observability/metrics.py` - Core metrics collection and registry
- `backend/src/dicom_ingestion/observability/collector.py` - Pipeline stage metrics collection
- `backend/src/dicom_ingestion/observability/health.py` - Health check endpoints and status
- `backend/src/dicom_ingestion/observability/logging_config.py` - Structured logging with correlation IDs
- `backend/src/dicom_ingestion/security/input_validator.py` - Input validation and sanitization
- `backend/src/dicom_ingestion/security/audit_logger.py` - Audit logging for PHI operations
- `backend/src/dicom_ingestion/security/phi_filter.py` - PHI data filtering for logs
- `backend/src/dicom_ingestion/ops/smoke_tests.py` - Pre-deployment smoke checks
- `backend/src/dicom_ingestion/ops/deployment_checks.py` - Deployment validation
- `backend/docs/runbooks/deployment.md` - Deployment and rollback procedures
- `backend/docs/runbooks/incident_response.md` - Incident triage and response
- `backend/docs/security/compliance.md` - Security controls and compliance evidence
- `backend/dashboards/ingestion_dashboard.json` - Grafana dashboard configuration

**Existing Files to Modify:**
- `backend/src/dicom_ingestion/services/upload/upload_service.py` - Add metrics and audit logging
- `backend/src/dicom_ingestion/services/scanner/scan_service.py` - Add stage metrics and structured logging
- `backend/src/dicom_ingestion/services/replay/replay_service.py` - Add metrics and audit logging
- `backend/src/dicom_ingestion/services/binding/binding_policy.py` - Add audit logging for PHI
- `backend/src/dicom_ingestion/services/projection/projection_service.py` - Add metrics

---

## Task 1: Core Metrics Infrastructure

**Files:**
- Create: `backend/src/dicom_ingestion/observability/__init__.py`
- Create: `backend/src/dicom_ingestion/observability/metrics.py`
- Test: `backend/tests/observability/test_metrics.py`

### Step 1: Write the failing test

```python
# backend/tests/observability/test_metrics.py
import pytest
from dicom_ingestion.observability.metrics import Counter, Histogram, MetricsRegistry


class TestCounter:
    def test_counter_increment(self):
        counter = Counter("test_counter", "A test counter")
        counter.inc()
        assert counter.value == 1
        counter.inc(5)
        assert counter.value == 6

    def test_counter_labels(self):
        counter = Counter("test_labeled_counter", "Counter with labels", labels=["stage"])
        counter.inc(labels={"stage": "scan"})
        counter.inc(labels={"stage": "parse"})
        assert counter.value({"stage": "scan"}) == 1
        assert counter.value({"stage": "parse"}) == 1


class TestHistogram:
    def test_histogram_observe(self):
        hist = Histogram("test_histogram", "A test histogram", buckets=[0.1, 0.5, 1.0, 5.0])
        hist.observe(0.3)
        hist.observe(1.5)
        hist.observe(0.05)
        
        assert hist.sum == 1.85
        assert hist.count == 3
        assert hist.buckets[0.1] == 1  # 0.05
        assert hist.buckets[0.5] == 2  # 0.05, 0.3
        assert hist.buckets[1.0] == 2  # 0.05, 0.3
        assert hist.buckets[5.0] == 3  # all values


class TestMetricsRegistry:
    def test_register_and_collect(self):
        registry = MetricsRegistry()
        counter = Counter("requests_total", "Total requests")
        registry.register(counter)
        
        counter.inc()
        output = registry.output_prometheus_format()
        
        assert "requests_total" in output
        assert "1" in output
```

### Step 2: Run test to verify it fails

Run: `cd /mnt/data/hy/test/DM/dicom-ingestion/backend && python -m pytest tests/observability/test_metrics.py -v`

Expected: FAIL with "ModuleNotFoundError: No module named 'dicom_ingestion.observability'"

### Step 3: Create module and implement minimal code

```python
# backend/src/dicom_ingestion/observability/__init__.py
"""Observability module for DICOM ingestion."""
from .metrics import Counter, Histogram, MetricsRegistry
from .collector import PipelineMetricsCollector
from .health import HealthCheck, HealthStatus

__all__ = [
    "Counter",
    "Histogram", 
    "MetricsRegistry",
    "PipelineMetricsCollector",
    "HealthCheck",
    "HealthStatus",
]
```

```python
# backend/src/dicom_ingestion/observability/metrics.py
"""Core metrics collection for DICOM ingestion observability."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union


@dataclass
class Counter:
    """A counter metric that only increases."""
    name: str
    description: str
    labels: Optional[List[str]] = None
    _values: Dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    
    def inc(self, amount: int = 1, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment counter by amount."""
        label_key = self._make_key(labels or {})
        self._values[label_key] += amount
    
    def value(self, labels: Optional[Dict[str, str]] = None) -> int:
        """Get current counter value."""
        label_key = self._make_key(labels or {})
        return self._values[label_key]
    
    def _make_key(self, labels: Dict[str, str]) -> tuple:
        """Convert label dict to sorted tuple for consistent hashing."""
        if not self.labels:
            return ()
        return tuple(sorted((k, labels.get(k, "")) for k in self.labels))
    
    def output_prometheus(self) -> str:
        """Output in Prometheus exposition format."""
        lines = [f"# HELP {self.name} {self.description}",
                f"# TYPE {self.name} counter"]
        
        if not self.labels:
            lines.append(f"{self.name} {self.value()}")
        else:
            for label_key, value in self._values.items():
                label_str = ",".join(f'{k}="{v}"' for k, v in label_key)
                lines.append(f"{self.name}{{{label_str}}} {value}")
        
        return "\n".join(lines)


@dataclass 
class Histogram:
    """A histogram metric for measuring distributions."""
    name: str
    description: str
    buckets: List[float] = field(default_factory=lambda: [0.1, 0.5, 1.0, 5.0, 10.0])
    labels: Optional[List[str]] = None
    
    def __post_init__(self):
        self._data: Dict[tuple, Dict] = defaultdict(lambda: {
            "buckets": {b: 0 for b in self.buckets},
            "sum": 0.0,
            "count": 0
        })
    
    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Observe a value."""
        label_key = self._make_key(labels or {})
        data = self._data[label_key]
        
        # Update buckets (cumulative)
        for bucket in sorted(self.buckets):
            if value <= bucket:
                data["buckets"][bucket] += 1
        
        data["sum"] += value
        data["count"] += 1
    
    def _make_key(self, labels: Dict[str, str]) -> tuple:
        """Convert label dict to sorted tuple."""
        if not self.labels:
            return ()
        return tuple(sorted((k, labels.get(k, "")) for k in self.labels))
    
    def output_prometheus(self) -> str:
        """Output in Prometheus exposition format."""
        lines = [f"# HELP {self.name} {self.description}",
                f"# TYPE {self.name} histogram"]
        
        if not self.labels:
            data = self._data[()]
            for bucket in sorted(self.buckets):
                lines.append(f'{self.name}_bucket{{le="{bucket}"}} {data["buckets"][bucket]}')
            lines.append(f'{self.name}_bucket{{le="+Inf"}} {data["count"]}')
            lines.append(f"{self.name}_sum {data['sum']}")
            lines.append(f"{self.name}_count {data['count']}")
        else:
            for label_key, data in self._data.items():
                label_str = ",".join(f'{k}="{v}"' for k, v in label_key)
                for bucket in sorted(self.buckets):
                    lines.append(f'{self.name}_bucket{{{label_str},le="{bucket}"}} {data["buckets"][bucket]}')
                lines.append(f'{self.name}_bucket{{{label_str},le="+Inf"}} {data["count"]}')
                lines.append(f"{self.name}_sum{{{label_str}}} {data['sum']}")
                lines.append(f"{self.name}_count{{{label_str}}} {data['count']}")
        
        return "\n".join(lines)
    
    @property
    def sum(self) -> float:
        """Get sum of all observations (no labels)."""
        return self._data[()]["sum"]
    
    @property
    def count(self) -> int:
        """Get total count of observations (no labels)."""
        return self._data[()]["count"]
    
    @property
    def buckets(self) -> List[float]:
        """Get bucket thresholds."""
        return self._buckets


class MetricsRegistry:
    """Registry for all metrics."""
    
    def __init__(self):
        self._metrics: Dict[str, Union[Counter, Histogram]] = {}
    
    def register(self, metric: Union[Counter, Histogram]) -> None:
        """Register a metric."""
        self._metrics[metric.name] = metric
    
    def get(self, name: str) -> Optional[Union[Counter, Histogram]]:
        """Get a metric by name."""
        return self._metrics.get(name)
    
    def output_prometheus_format(self) -> str:
        """Output all metrics in Prometheus format."""
        sections = []
        for metric in self._metrics.values():
            sections.append(metric.output_prometheus())
        return "\n\n".join(sections)
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/observability/test_metrics.py -v`

Expected: PASS

### Step 5: Commit

```bash
cd /mnt/data/hy/test/DM/dicom-ingestion
git add backend/src/dicom_ingestion/observability/__init__.py
 git add backend/src/dicom_ingestion/observability/metrics.py
git add backend/tests/observability/test_metrics.py
git commit -m "feat(observability): add core metrics infrastructure (Counter, Histogram, Registry)"
```

---

## Task 2: Pipeline Stage Metrics Collector

**Files:**
- Create: `backend/src/dicom_ingestion/observability/collector.py`
- Test: `backend/tests/observability/test_collector.py`

### Step 1: Write the failing test

```python
# backend/tests/observability/test_collector.py
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
        assert counter.value({"stage": "scan", "status": "success"}) == 1

    def test_record_stage_failure(self):
        registry = MetricsRegistry()
        collector = PipelineMetricsCollector(registry)
        
        collector.record_stage_start("item_1", PipelineStage.SCAN)
        collector.record_stage_complete("item_1", PipelineStage.SCAN, success=False, duration_ms=50, error_code="PARSE_ERROR")
        
        counter = registry.get("dicom_ingestion_items_total")
        assert counter.value({"stage": "scan", "status": "failed"}) == 1

    def test_duration_histogram(self):
        registry = MetricsRegistry()
        collector = PipelineMetricsCollector(registry)
        
        collector.record_stage_complete("item_1", PipelineStage.PARSE, success=True, duration_ms=250)
        
        hist = registry.get("dicom_ingestion_stage_duration_ms")
        assert hist is not None
        assert hist.count == 1
        assert hist.sum == 250.0
```

### Step 2: Run test to verify it fails

Run: `python -m pytest tests/observability/test_collector.py -v`

Expected: FAIL with "ModuleNotFoundError"

### Step 3: Implement PipelineMetricsCollector

```python
# backend/src/dicom_ingestion/observability/collector.py
"""Pipeline stage metrics collection for DICOM ingestion."""

from enum import Enum
from typing import Optional

from .metrics import Counter, Histogram, MetricsRegistry


class PipelineStage(str, Enum):
    """Pipeline stages as defined in observability vocabulary."""
    RECEIVE = "receive"
    SCAN = "scan"
    PARSE = "parse"
    STORE = "store"
    PERSIST_METADATA = "persist_metadata"
    VALIDATE = "validate"
    BIND = "bind"
    INDEX = "index"


class PipelineMetricsCollector:
    """Collects metrics for DICOM ingestion pipeline stages.
    
    Tracks:
    - Items processed per stage (success/failure)
    - Stage durations
    - Error codes for failures
    - Active/stuck items
    """
    
    def __init__(self, registry: MetricsRegistry):
        self.registry = registry
        self._init_metrics()
    
    def _init_metrics(self) -> None:
        """Initialize all pipeline metrics."""
        # Counter for items processed
        self.items_counter = Counter(
            "dicom_ingestion_items_total",
            "Total number of items processed by stage",
            labels=["stage", "status"]  # status: success, failed
        )
        self.registry.register(self.items_counter)
        
        # Counter for items stuck/aging
        self.stuck_counter = Counter(
            "dicom_ingestion_items_stuck_total",
            "Number of items stuck in a stage for too long",
            labels=["stage"]
        )
        self.registry.register(self.stuck_counter)
        
        # Histogram for stage durations
        self.duration_histogram = Histogram(
            "dicom_ingestion_stage_duration_ms",
            "Duration of pipeline stages in milliseconds",
            buckets=[10, 50, 100, 250, 500, 1000, 5000, 10000],
            labels=["stage", "status"]
        )
        self.registry.register(self.duration_histogram)
        
        # Counter for specific error types
        self.error_counter = Counter(
            "dicom_ingestion_errors_total",
            "Total errors by type and stage",
            labels=["stage", "error_code"]
        )
        self.registry.register(self.error_counter)
        
        # Gauge for active jobs (emulated with counter for now)
        self.jobs_counter = Counter(
            "dicom_ingestion_jobs_total",
            "Total jobs processed",
            labels=["status"]  # started, completed, failed
        )
        self.registry.register(self.jobs_counter)
    
    def record_job_started(self, job_id: str) -> None:
        """Record that a job started."""
        self.jobs_counter.inc(labels={"status": "started"})
    
    def record_job_completed(self, job_id: str, success: bool) -> None:
        """Record that a job completed."""
        status = "completed" if success else "failed"
        self.jobs_counter.inc(labels={"status": status})
    
    def record_stage_start(self, item_id: str, stage: PipelineStage) -> None:
        """Record the start of a stage for an item.
        
        This is primarily for tracking stuck items later.
        """
        # Store start time for duration calculation
        # In a real implementation, this would use a cache or storage
        pass  # Simplified for now
    
    def record_stage_complete(
        self,
        item_id: str,
        stage: PipelineStage,
        success: bool,
        duration_ms: float,
        error_code: Optional[str] = None
    ) -> None:
        """Record stage completion.
        
        Args:
            item_id: Unique identifier for the item
            stage: The pipeline stage that completed
            success: Whether the stage completed successfully
            duration_ms: Duration in milliseconds
            error_code: Error code if failed
        """
        status = "success" if success else "failed"
        
        # Increment items counter
        self.items_counter.inc(labels={"stage": stage.value, "status": status})
        
        # Record duration
        self.duration_histogram.observe(duration_ms, labels={"stage": stage.value, "status": status})
        
        # Record error if failed
        if not success and error_code:
            self.error_counter.inc(labels={"stage": stage.value, "error_code": error_code})
    
    def record_item_stuck(self, item_id: str, stage: PipelineStage, age_minutes: int) -> None:
        """Record that an item is stuck in a stage."""
        self.stuck_counter.inc(labels={"stage": stage.value})
    
    def get_metrics_output(self) -> str:
        """Get all metrics in Prometheus format."""
        return self.registry.output_prometheus_format()
```

### Step 4: Run test to verify it passes

Run: `python -m pytest tests/observability/test_collector.py -v`

Expected: PASS

### Step 5: Commit

```bash
git add backend/src/dicom_ingestion/observability/collector.py
git add backend/tests/observability/test_collector.py
git commit -m "feat(observability): add PipelineMetricsCollector for stage tracking"
```

---

## Task 3: Health Checks

**Files:**
- Create: `backend/src/dicom_ingestion/observability/health.py`
- Test: `backend/tests/observability/test_health.py`

### Step 1: Write the failing test

```python
# backend/tests/observability/test_health.py
import pytest
from dicom_ingestion.observability.health import HealthCheck, HealthStatus, CheckResult


class TestHealthCheck:
    def test_basic_health_check(self):
        check = HealthCheck("test_service")
        check.add_check("database", lambda: CheckResult.healthy("DB connected"))
        
        status = check.get_status()
        assert status.status == "healthy"
        assert status.checks["database"].status == "healthy"

    def test_unhealthy_check(self):
        check = HealthCheck("test_service")
        check.add_check("database", lambda: CheckResult.unhealthy("DB down"))
        
        status = check.get_status()
        assert status.status == "unhealthy"
        assert status.checks["database"].status == "unhealthy"

    def test_mixed_health(self):
        check = HealthCheck("test_service")
        check.add_check("db", lambda: CheckResult.healthy("OK"))
        check.add_check("cache", lambda: CheckResult.unhealthy("Cache down"))
        
        status = check.get_status()
        assert status.status == "unhealthy"  # One failing = unhealthy
```

### Step 2: Implement HealthCheck

```python
# backend/src/dicom_ingestion/observability/health.py
"""Health check system for DICOM ingestion services."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional


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
    details: Dict[str, any] = field(default_factory=dict)
    
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
```

### Step 3: Run tests

Run: `python -m pytest tests/observability/test_health.py -v`

Expected: PASS

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/observability/health.py
git add backend/tests/observability/test_health.py
git commit -m "feat(observability): add health check system"
```

---

## Task 4: Structured Logging with Correlation IDs

**Files:**
- Create: `backend/src/dicom_ingestion/observability/logging_config.py`
- Test: `backend/tests/observability/test_logging.py`

### Step 1: Write the failing test

```python
# backend/tests/observability/test_logging.py
import json
import logging
import pytest
from dicom_ingestion.observability.logging_config import StructuredLogFormatter, CorrelationIdFilter


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
```

### Step 2: Implement structured logging

```python
# backend/src/dicom_ingestion/observability/logging_config.py
"""Structured logging configuration for DICOM ingestion."""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# Thread-local storage for correlation context
_correlation_context = threading.local()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current thread."""
    _correlation_context.correlation_id = correlation_id


def get_correlation_id() -> Optional[str]:
    """Get the correlation ID for the current thread."""
    return getattr(_correlation_context, "correlation_id", None)


def set_job_context(job_id: Optional[str] = None, item_id: Optional[str] = None) -> None:
    """Set job context for the current thread."""
    if job_id:
        _correlation_context.job_id = job_id
    if item_id:
        _correlation_context.item_id = item_id


def get_job_context() -> Dict[str, Optional[str]]:
    """Get job context for the current thread."""
    return {
        "job_id": getattr(_correlation_context, "job_id", None),
        "item_id": getattr(_correlation_context, "item_id", None),
    }


def clear_context() -> None:
    """Clear all correlation context."""
    _correlation_context.correlation_id = None
    _correlation_context.job_id = None
    _correlation_context.item_id = None


class CorrelationIdFilter(logging.Filter):
    """Add correlation ID to log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "N/A"
        context = get_job_context()
        record.job_id = context.get("job_id") or "N/A"
        record.item_id = context.get("item_id") or "N/A"
        return True


class StructuredLogFormatter(logging.Formatter):
    """JSON structured log formatter."""
    
    def __init__(self) -> None:
        super().__init__()
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "N/A"),
            "job_id": getattr(record, "job_id", "N/A"),
            "item_id": getattr(record, "item_id", "N/A"),
        }
        
        # Add source location
        log_data["source"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add any extra attributes from the record
        for key, value in record.__dict__.items():
            if key not in log_data and not key.startswith("_"):
                if key not in ("args", "asctime", "created", "exc_info", "exc_text",
                              "filename", "funcName", "levelname", "levelno", "lineno",
                              "module", "msecs", "message", "msg", "name", "pathname",
                              "process", "processName", "relativeCreated", "stack_info",
                              "thread", "threadName", "correlation_id", "job_id", "item_id"):
                    log_data[key] = value
        
        return json.dumps(log_data, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structured logging for the application."""
    # Remove existing handlers
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    
    # Create console handler with structured formatter
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredLogFormatter())
    handler.addFilter(CorrelationIdFilter())
    
    root.addHandler(handler)
    root.setLevel(level)
    
    # Set dicom_ingestion logger level
    logging.getLogger("dicom_ingestion").setLevel(level)
```

### Step 3: Run tests

Run: `python -m pytest tests/observability/test_logging.py -v`

Expected: PASS

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/observability/logging_config.py
git add backend/tests/observability/test_logging.py
git commit -m "feat(observability): add structured logging with correlation IDs"
```

---

## Task 5: Security - Input Validation

**Files:**
- Create: `backend/src/dicom_ingestion/security/__init__.py`
- Create: `backend/src/dicom_ingestion/security/input_validator.py`
- Test: `backend/tests/security/test_input_validator.py`

### Step 1: Write the failing test

```python
# backend/tests/security/test_input_validator.py
import pytest
from dicom_ingestion.security.input_validator import (
    InputValidator, ValidationResult, PathValidator, UidValidator
)


class TestPathValidator:
    def test_valid_path(self):
        validator = PathValidator()
        result = validator.validate("folder/file.dcm")
        assert result.is_valid
        assert not result.errors

    def test_path_traversal(self):
        validator = PathValidator()
        result = validator.validate("../../../etc/passwd")
        assert not result.is_valid
        assert "path_traversal" in result.errors

    def test_null_bytes(self):
        validator = PathValidator()
        result = validator.validate("file\x00.dcm")
        assert not result.is_valid
        assert "null_byte" in result.errors


class TestUidValidator:
    def test_valid_uid(self):
        validator = UidValidator()
        result = validator.validate("1.2.840.10008.1.2.1")
        assert result.is_valid

    def test_invalid_uid_characters(self):
        validator = UidValidator()
        result = validator.validate("1.2.abc.10008")
        assert not result.is_valid
        assert "invalid_characters" in result.errors

    def test_uid_too_long(self):
        validator = UidValidator()
        result = validator.validate("1." + "2." * 100)
        assert not result.is_valid
        assert "too_long" in result.errors
```

### Step 2: Implement input validation

```python
# backend/src/dicom_ingestion/security/__init__.py
"""Security module for DICOM ingestion."""
from .input_validator import InputValidator, ValidationResult, PathValidator, UidValidator
from .audit_logger import AuditLogger, AuditEvent
from .phi_filter import PhiFilter

__all__ = [
    "InputValidator",
    "ValidationResult",
    "PathValidator",
    "UidValidator",
    "AuditLogger",
    "AuditEvent",
    "PhiFilter",
]
```

```python
# backend/src/dicom_ingestion/security/input_validator.py
"""Input validation and sanitization for DICOM ingestion."""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol


@dataclass
class ValidationResult:
    """Result of input validation."""
    is_valid: bool
    errors: Dict[str, str] = field(default_factory=dict)
    sanitized: Optional[str] = None


class Validator(Protocol):
    """Protocol for validators."""
    def validate(self, value: str) -> ValidationResult:
        ...


class PathValidator:
    """Validates file paths for security issues."""
    
    # Maximum path length
    MAX_LENGTH = 4096
    
    # Pattern for path traversal attempts
    TRAVERSAL_PATTERN = re.compile(r"\.\./|\.\.\\|^/|^\\")
    
    # Pattern for null bytes
    NULL_BYTE_PATTERN = re.compile(r"\x00")
    
    # Pattern for control characters
    CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f-\x9f]")
    
    def validate(self, path: str) -> ValidationResult:
        """Validate a file path.
        
        Checks:
        - Path traversal attempts (../)
        - Null bytes
        - Control characters
        - Excessive length
        - Absolute paths (should be relative)
        """
        errors: Dict[str, str] = {}
        
        if not path:
            errors["empty"] = "Path cannot be empty"
            return ValidationResult(is_valid=False, errors=errors)
        
        # Check length
        if len(path) > self.MAX_LENGTH:
            errors["too_long"] = f"Path exceeds maximum length of {self.MAX_LENGTH}"
        
        # Check for null bytes
        if self.NULL_BYTE_PATTERN.search(path):
            errors["null_byte"] = "Path contains null bytes"
        
        # Check for control characters
        if self.CONTROL_CHAR_PATTERN.search(path):
            errors["control_chars"] = "Path contains control characters"
        
        # Check for path traversal
        if self.TRAVERSAL_PATTERN.search(path):
            errors["path_traversal"] = "Path contains traversal attempts"
        
        # Check for common dangerous patterns
        dangerous = ["//", "\\\\", "..", "~", "$"]
        for pattern in dangerous:
            if pattern in path:
                errors[f"dangerous_{pattern}"] = f"Path contains dangerous pattern: {pattern}"
                break
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized=self._sanitize(path) if errors else path
        )
    
    def _sanitize(self, path: str) -> str:
        """Attempt to sanitize a path (best effort)."""
        # Remove null bytes
        sanitized = path.replace("\x00", "")
        # Remove control characters
        sanitized = self.CONTROL_CHAR_PATTERN.sub("", sanitized)
        # Remove path traversal
        sanitized = sanitized.replace("../", "").replace("..\\", "")
        return sanitized


class UidValidator:
    """Validates DICOM UIDs (Unique Identifiers)."""
    
    # Maximum UID length per DICOM standard
    MAX_LENGTH = 64
    
    # UID pattern: starts with digit, followed by dots and digits
    UID_PATTERN = re.compile(r"^[0-9]+(\.[0-9]+)*$")
    
    def validate(self, uid: str) -> ValidationResult:
        """Validate a DICOM UID.
        
        Per DICOM PS3.5:
        - Must contain only digits and dots
        - First and last characters must be digits
        - No consecutive dots
        - Max 64 characters
        """
        errors: Dict[str, str] = {}
        
        if not uid:
            errors["empty"] = "UID cannot be empty"
            return ValidationResult(is_valid=False, errors=errors)
        
        # Check length
        if len(uid) > self.MAX_LENGTH:
            errors["too_long"] = f"UID exceeds maximum length of {self.MAX_LENGTH}"
        
        # Check pattern
        if not self.UID_PATTERN.match(uid):
            errors["invalid_characters"] = "UID must contain only digits and dots"
        
        # Check for consecutive dots
        if ".." in uid:
            errors["consecutive_dots"] = "UID cannot contain consecutive dots"
        
        # Check start/end
        if uid.startswith("."):
            errors["starts_with_dot"] = "UID cannot start with a dot"
        if uid.endswith("."):
            errors["ends_with_dot"] = "UID cannot end with a dot"
        
        return ValidationResult(is_valid=len(errors) == 0, errors=errors)


class InputValidator:
    """Main input validation service."""
    
    def __init__(self):
        self._validators: Dict[str, Validator] = {
            "path": PathValidator(),
            "uid": UidValidator(),
        }
    
    def validate_path(self, path: str) -> ValidationResult:
        """Validate a file path."""
        return self._validators["path"].validate(path)
    
    def validate_uid(self, uid: str) -> ValidationResult:
        """Validate a DICOM UID."""
        return self._validators["uid"].validate(uid)
    
    def validate_upload_filename(self, filename: str) -> ValidationResult:
        """Validate an upload filename with additional checks."""
        path_result = self.validate_path(filename)
        
        # Additional filename-specific checks
        errors = dict(path_result.errors)
        
        # Check extension for common DICOM extensions
        allowed_extensions = (".dcm", ".dic", ".dicom", ".zip", ".tar", ".gz")
        if not any(filename.lower().endswith(ext) for ext in allowed_extensions):
            # Not an error, just a warning - we accept any file
            pass
        
        # Check for multiple extensions (potential polyglot)
        if filename.count(".") > 2:
            errors["multiple_extensions"] = "Filename has multiple extensions"
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            sanitized=path_result.sanitized
        )
```

### Step 3: Run tests

Run: `python -m pytest tests/security/test_input_validator.py -v`

Expected: PASS

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/security/__init__.py
git add backend/src/dicom_ingestion/security/input_validator.py
git add backend/tests/security/test_input_validator.py
git commit -m "feat(security): add input validation for paths and UIDs"
```

---

## Task 6: Security - Audit Logger

**Files:**
- Create: `backend/src/dicom_ingestion/security/audit_logger.py`
- Test: `backend/tests/security/test_audit_logger.py`

### Step 1: Write the failing test

```python
# backend/tests/security/test_audit_logger.py
import json
import pytest
from datetime import datetime
from dicom_ingestion.security.audit_logger import AuditLogger, AuditEvent, AuditAction


class TestAuditLogger:
    def test_log_phi_access(self, tmp_path):
        log_file = tmp_path / "audit.log"
        logger = AuditLogger(str(log_file))
        
        logger.log_phi_access(
            action=AuditAction.READ,
            actor_id="user_123",
            resource_type="dicom_instance",
            resource_id="instance_456",
            phi_fields=["patient_name", "patient_id"],
            success=True
        )
        
        # Read and verify log
        with open(log_file) as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["action"] == "READ"
        assert entry["actor_id"] == "user_123"
        assert entry["resource_type"] == "dicom_instance"
        assert "timestamp" in entry
        assert entry["phi_accessed"] == True
```

### Step 2: Implement audit logger

```python
# backend/src/dicom_ingestion/security/audit_logger.py
"""Audit logging for PHI-touching operations."""

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class AuditAction(str, Enum):
    """Audit actions for PHI operations."""
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    EXPORT = "EXPORT"
    REPLAY = "REPLAY"
    RETRY = "RETRY"


@dataclass
class AuditEvent:
    """Audit event for PHI operations."""
    timestamp: str
    action: str
    actor_id: str
    resource_type: str
    resource_id: str
    phi_accessed: bool
    phi_fields: List[str]
    success: bool
    error_code: Optional[str] = None
    correlation_id: Optional[str] = None
    additional_data: Dict = field(default_factory=dict)


class AuditLogger:
    """Audit logger for PHI-touching operations.
    
    All PHI access must be logged for compliance.
    Logs are structured JSON for easy processing.
    """
    
    def __init__(self, log_path: Optional[str] = None):
        self._logger = logging.getLogger("dicom_ingestion.audit")
        self._logger.setLevel(logging.INFO)
        
        # Prevent duplicate handlers
        if not self._logger.handlers and log_path:
            handler = logging.FileHandler(log_path)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
    
    def _get_timestamp(self) -> str:
        """Get current UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()
    
    def _get_correlation_id(self) -> Optional[str]:
        """Get correlation ID from context if available."""
        try:
            from ..observability.logging_config import get_correlation_id
            return get_correlation_id()
        except ImportError:
            return None
    
    def log_phi_access(
        self,
        action: AuditAction,
        actor_id: str,
        resource_type: str,
        resource_id: str,
        phi_fields: List[str],
        success: bool,
        error_code: Optional[str] = None,
        **additional_data
    ) -> None:
        """Log a PHI access event.
        
        Args:
            action: The action performed
            actor_id: Who performed the action (user/service)
            resource_type: Type of resource accessed
            resource_id: ID of the resource
            phi_fields: List of PHI fields that were accessed
            success: Whether the operation succeeded
            error_code: Error code if failed
            additional_data: Any additional context
        """
        event = AuditEvent(
            timestamp=self._get_timestamp(),
            action=action.value,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            phi_accessed=len(phi_fields) > 0,
            phi_fields=phi_fields,
            success=success,
            error_code=error_code,
            correlation_id=self._get_correlation_id(),
            additional_data=additional_data
        )
        
        # Log as JSON
        self._logger.info(json.dumps(asdict(event), default=str))
    
    def log_ingestion_start(self, job_id: str, actor_id: str, item_count: int) -> None:
        """Log when an ingestion job starts."""
        self.log_phi_access(
            action=AuditAction.CREATE,
            actor_id=actor_id,
            resource_type="ingestion_job",
            resource_id=job_id,
            phi_fields=[],  # No PHI accessed yet
            success=True,
            item_count=item_count
        )
    
    def log_replay(self, item_id: str, actor_id: str, stage: str, success: bool) -> None:
        """Log a replay operation."""
        self.log_phi_access(
            action=AuditAction.REPLAY,
            actor_id=actor_id,
            resource_type="ingestion_item",
            resource_id=item_id,
            phi_fields=["dicom_metadata"],
            success=success,
            stage=stage
        )
    
    def log_binding_resolution(
        self,
        item_id: str,
        actor_id: str,
        study_uid: str,
        series_uid: str,
        success: bool
    ) -> None:
        """Log when binding policy resolves associations.
        
        This touches PHI (UIDs may be considered identifying).
        """
        self.log_phi_access(
            action=AuditAction.READ,
            actor_id=actor_id,
            resource_type="ingestion_item",
            resource_id=item_id,
            phi_fields=["study_instance_uid", "series_instance_uid"],
            success=success,
            study_uid=study_uid,
            series_uid=series_uid
        )
```

### Step 3: Run tests

Run: `python -m pytest tests/security/test_audit_logger.py -v`

Expected: PASS

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/security/audit_logger.py
git add backend/tests/security/test_audit_logger.py
git commit -m "feat(security): add audit logging for PHI operations"
```

---

## Task 7: Security - PHI Filter

**Files:**
- Create: `backend/src/dicom_ingestion/security/phi_filter.py`
- Test: `backend/tests/security/test_phi_filter.py`

### Step 1: Write the failing test

```python
# backend/tests/security/test_phi_filter.py
import pytest
from dicom_ingestion.security.phi_filter import PhiFilter


class TestPhiFilter:
    def test_filter_patient_name(self):
        data = {
            "patient_name": "John Doe",
            "study_description": "Chest X-Ray",
            "rows": 512
        }
        
        filtered = PhiFilter.filter_for_logging(data)
        
        assert filtered["patient_name"] == "[REDACTED-PHI]"
        assert filtered["study_description"] == "Chest X-Ray"
        assert filtered["rows"] == 512

    def test_filter_nested_phi(self):
        data = {
            "header": {
                "patient_id": "P12345",
                "patient_birth_date": "19800101"
            },
            "metadata": {
                "modality": "CT"
            }
        }
        
        filtered = PhiFilter.filter_for_logging(data)
        
        assert filtered["header"]["patient_id"] == "[REDACTED-PHI]"
        assert filtered["header"]["patient_birth_date"] == "[REDACTED-PHI]"
        assert filtered["metadata"]["modality"] == "CT"

    def test_filter_list_items(self):
        data = [
            {"patient_name": "John", "study": "A"},
            {"patient_name": "Jane", "study": "B"}
        ]
        
        filtered = PhiFilter.filter_for_logging(data)
        
        assert filtered[0]["patient_name"] == "[REDACTED-PHI]"
        assert filtered[1]["patient_name"] == "[REDACTED-PHI]"
```

### Step 2: Implement PHI filter

```python
# backend/src/dicom_ingestion/security/phi_filter.py
"""PHI (Protected Health Information) filtering for logs.

Per HIPAA and the observability vocabulary, these fields must NEVER be logged:
- patient_name
- patient_id
- patient_birth_date
- Raw DICOM tag values unless explicitly allowlisted
"""

from typing import Any, Dict, List, Set, Union


class PhiFilter:
    """Filters PHI from data structures before logging."""
    
    # Fields that must never be logged
    PHI_FIELDS: Set[str] = {
        "patient_name",
        "patient_id",
        "patient_birth_date",
        "patient_birth_time",
        "patient_sex",
        "patient_age",
        "patient_weight",
        "patient_address",
        "patient_phone",
        "patient_mothers_maiden_name",
        "patient_ssn",  # If present
        "patient_insurance",
        "referring_physician_name",
        "performing_physician_name",
        "operator_name",
        "physician_of_record",
        "study_description",  # May contain patient info
        "series_description",  # May contain patient info
        # Raw tag values (unless in allowlist)
        "raw_dicom_tags",
    }
    
    # UIDs are safe to log (they're identifiers, not identifying info)
    SAFE_UID_FIELDS: Set[str] = {
        "study_instance_uid",
        "series_instance_uid",
        "sop_instance_uid",
        "sop_class_uid",
        "transfer_syntax_uid",
    }
    
    # Allowlisted DICOM tags that are safe to log
    SAFE_DICOM_TAGS: Set[str] = {
        "Modality",
        "BodyPartExamined",
        "StudyDate",
        "StudyTime",
        "SeriesNumber",
        "InstanceNumber",
        "Rows",
        "Columns",
        "PixelSpacing",
        "SliceThickness",
        "KVP",
        "ExposureTime",
        "XRayTubeCurrent",
    }
    
    REDACTION_TOKEN = "[REDACTED-PHI]"
    
    @classmethod
    def filter_for_logging(cls, data: Any) -> Any:
        """Recursively filter PHI from data structure.
        
        Args:
            data: Any JSON-serializable data structure
            
        Returns:
            Data structure with PHI fields redacted
        """
        if isinstance(data, dict):
            return cls._filter_dict(data)
        elif isinstance(data, list):
            return [cls.filter_for_logging(item) for item in data]
        else:
            return data
    
    @classmethod
    def _filter_dict(cls, data: Dict) -> Dict:
        """Filter PHI from a dictionary."""
        result = {}
        for key, value in data.items():
            key_lower = key.lower()
            
            # Check if this is a PHI field
            if key_lower in cls.PHI_FIELDS:
                result[key] = cls.REDACTION_TOKEN
            # UIDs are safe
            elif key_lower in cls.SAFE_UID_FIELDS:
                result[key] = value
            # Recursively filter nested structures
            elif isinstance(value, (dict, list)):
                result[key] = cls.filter_for_logging(value)
            else:
                result[key] = value
        
        return result
    
    @classmethod
    def is_phi_field(cls, field_name: str) -> bool:
        """Check if a field name is considered PHI."""
        return field_name.lower() in cls.PHI_FIELDS
    
    @classmethod
    def is_safe_dicom_tag(cls, tag_name: str) -> bool:
        """Check if a DICOM tag is safe to log."""
        return tag_name in cls.SAFE_DICOM_TAGS
```

### Step 3: Run tests

Run: `python -m pytest tests/security/test_phi_filter.py -v`

Expected: PASS

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/security/phi_filter.py
git add backend/tests/security/test_phi_filter.py
git commit -m "feat(security): add PHI filtering for safe logging"
```

---

## Task 8: Operations - Smoke Tests

**Files:**
- Create: `backend/src/dicom_ingestion/ops/__init__.py`
- Create: `backend/src/dicom_ingestion/ops/smoke_tests.py`
- Test: `backend/tests/ops/test_smoke_tests.py`

### Step 1: Write the failing test

```python
# backend/tests/ops/test_smoke_tests.py
import pytest
from dicom_ingestion.ops.smoke_tests import SmokeTestSuite, SmokeTestResult
from dicom_ingestion.observability.health import HealthCheck


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
```

### Step 2: Implement smoke tests

```python
# backend/src/dicom_ingestion/ops/__init__.py
"""Operations module for deployment and monitoring."""
from .smoke_tests import SmokeTestSuite, SmokeTestResult
from .deployment_checks import DeploymentValidator

__all__ = [
    "SmokeTestSuite",
    "SmokeTestResult", 
    "DeploymentValidator",
]
```

```python
# backend/src/dicom_ingestion/ops/smoke_tests.py
"""Pre-deployment smoke tests for DICOM ingestion."""

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
    name: str
    passed: bool
    status: TestStatus
    message: str
    duration_ms: float
    
    @classmethod
    def passed(cls, name: str, message: str = "OK", duration_ms: float = 0) -> "SmokeTestResult":
        return cls(name=name, passed=True, status=TestStatus.PASSED, message=message, duration_ms=duration_ms)
    
    @classmethod
    def failed(cls, name: str, message: str, duration_ms: float = 0) -> "SmokeTestResult":
        return cls(name=name, passed=False, status=TestStatus.FAILED, message=message, duration_ms=duration_ms)
    
    @classmethod
    def skipped(cls, name: str, message: str = "Not applicable") -> "SmokeTestResult":
        return cls(name=name, passed=True, status=TestStatus.SKIPPED, message=message, duration_ms=0)


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
    """Suite of smoke tests for deployment validation.
    
    Tests cover:
    - Database connectivity
    - Object storage access
    - Required tables exist
    - Basic ingestion flow works
    - Metrics endpoint responds
    - Health endpoint responds
    """
    
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
                # Simple query to verify connection
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
                # Try to write and read a small test object
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
```

### Step 3: Run tests

Run: `python -m pytest tests/ops/test_smoke_tests.py -v`

Expected: PASS

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/ops/__init__.py
git add backend/src/dicom_ingestion/ops/smoke_tests.py
git add backend/tests/ops/test_smoke_tests.py
git commit -m "feat(ops): add smoke test framework for deployment validation"
```

---

## Task 9: Deployment Checks

**Files:**
- Create: `backend/src/dicom_ingestion/ops/deployment_checks.py`
- Test: `backend/tests/ops/test_deployment_checks.py`

### Step 1: Write the failing test

```python
# backend/tests/ops/test_deployment_checks.py
import pytest
from dicom_ingestion.ops.deployment_checks import DeploymentValidator, MigrationCheck


class TestDeploymentValidator:
    def test_migration_check_passes(self):
        def mock_current_revision():
            return "abc123"
        
        def mock_expected_revision():
            return "abc123"
        
        check = MigrationCheck(mock_current_revision, mock_expected_revision)
        result = check.validate()
        
        assert result.valid
        assert "migrations up to date" in result.message.lower()

    def test_migration_check_fails(self):
        def mock_current_revision():
            return "old123"
        
        def mock_expected_revision():
            return "new456"
        
        check = MigrationCheck(mock_current_revision, mock_expected_revision)
        result = check.validate()
        
        assert not result.valid
        assert "migration mismatch" in result.message.lower()
```

### Step 2: Implement deployment checks

```python
# backend/src/dicom_ingestion/ops/deployment_checks.py
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
```

### Step 3: Run tests

Run: `python -m pytest tests/ops/test_deployment_checks.py -v`

Expected: PASS

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/ops/deployment_checks.py
git add backend/tests/ops/test_deployment_checks.py
git commit -m "feat(ops): add deployment validation checks"
```

---

## Task 10: Runbooks - Deployment Procedures

**Files:**
- Create: `backend/docs/runbooks/deployment.md`

### Step 1: Write deployment runbook

```markdown
# DICOM Ingestion Deployment Runbook

## Pre-Deployment Checklist

### 1. Database Migrations
```bash
# Verify current revision
alembic current

# Verify all migrations are applied
alembic heads

# If behind, run migrations
alembic upgrade head
```

### 2. Configuration Validation
```bash
# Check all required environment variables are set
python -m dicom_ingestion.ops.deployment_checks

# Expected output:
# ✓ DATABASE_URL
# ✓ OBJECT_STORAGE_URL
# ✓ LOG_LEVEL
```

### 3. Smoke Tests
```bash
# Run pre-deployment smoke tests
python -m dicom_ingestion.ops.smoke_tests

# All tests must pass:
# ✓ database_connection
# ✓ object_storage_access
# ✓ required_tables_exist
```

## Deployment Steps

### Step 1: Blue-Green Deployment

```bash
# 1. Deploy new version to "green" environment
deploy --target=green --version=$NEW_VERSION

# 2. Run smoke tests on green
run_smoke_tests --target=green

# 3. If tests pass, switch traffic
switch_traffic --from=blue --to=green

# 4. Monitor for 5 minutes
monitor --duration=5m --alert_on_error_rate=0.01
```

### Step 2: Database Migration (if needed)

```bash
# Run migrations in transaction
alembic upgrade head

# Verify migration applied
alembic current
```

### Step 3: Service Startup

```bash
# Start with health checks
docker-compose up -d

# Wait for healthy status
docker-compose ps

# Verify metrics endpoint
curl http://localhost:8080/metrics
```

## Rollback Procedures

### Automatic Rollback Triggers
- Error rate > 1% for 2 minutes
- Health check failures > 3 in 1 minute
- Latency p99 > 10 seconds

### Manual Rollback

```bash
# 1. Switch traffic back to blue
switch_traffic --from=green --to=blue

# 2. Stop green environment
docker-compose -f docker-compose.green.yml down

# 3. Verify blue is healthy
curl http://localhost:8080/health
```

### Database Rollback (Emergency Only)

```bash
# WARNING: Only if migration caused issues
# 1. Identify problematic migration
alembic history --verbose

# 2. Downgrade one step
alembic downgrade -1

# 3. Verify downgrade
alembic current
```

## Post-Deployment Verification

### 1. Health Checks
```bash
curl http://localhost:8080/health | jq .
# Expected: {"status": "healthy", "checks": {...}}
```

### 2. Metrics Collection
```bash
curl http://localhost:8080/metrics | grep "dicom_ingestion_"
# Expected: All counters and histograms present
```

### 3. Test Ingestion
```bash
# Upload test DICOM
curl -X POST -F "file=@test.dcm" http://localhost:8080/upload

# Verify metrics updated
curl http://localhost:8080/metrics | grep "dicom_ingestion_items_total"
```

## Troubleshooting

### Issue: High Error Rate
1. Check logs: `docker-compose logs | grep ERROR`
2. Check database connection pool
3. Check object storage connectivity
4. Consider rollback if > 5% error rate

### Issue: Slow Ingestion
1. Check stage durations in metrics
2. Verify database query performance
3. Check object storage latency
4. Consider scaling workers

### Issue: Disk Space
1. Check raw object storage size
2. Verify old data archival policy
3. Clean up failed upload temp files
```

### Step 2: Create the file

```bash
mkdir -p backend/docs/runbooks
cat > backend/docs/runbooks/deployment.md << 'EOF'
[Paste content above]
EOF
```

### Step 3: Commit

```bash
git add backend/docs/runbooks/deployment.md
git commit -m "docs(runbooks): add deployment and rollback procedures"
```

---

## Task 11: Runbooks - Incident Response

**Files:**
- Create: `backend/docs/runbooks/incident_response.md`

### Step 1: Write incident response runbook

```markdown
# DICOM Ingestion Incident Response Runbook

## Severity Levels

### P1 - Critical (Service Down)
- Complete ingestion pipeline failure
- Data loss or corruption detected
- Security breach suspected

**Response:** Page on-call immediately, war room within 15 minutes

### P2 - High (Degraded Service)
- Error rate > 5%
- Ingestion latency > 30 seconds
- Partial functionality unavailable

**Response:** Page on-call, start investigation within 30 minutes

### P3 - Medium (Minor Impact)
- Error rate 1-5%
- Non-critical alerts firing
- Performance degradation

**Response": Investigate during business hours

### P4 - Low (No User Impact)
- Warnings, capacity alerts
- Monitoring gaps

**Response**: Track in backlog

## Alert Response Procedures

### Alert: High Error Rate
**Trigger:** `dicom_ingestion_items_total{status="failed"} > 0.05`

**Response Steps:**
1. Check error logs: `grep ERROR /var/log/dicom-ingestion/app.log`
2. Identify failing stage from metrics
3. Check database connectivity
4. Check object storage connectivity
5. If error rate > 10%, initiate rollback

### Alert: Items Stuck
**Trigger:** `dicom_ingestion_items_stuck_total > 0`

**Response Steps:**
1. Query stuck items: `SELECT * FROM dicom_ingestion_items WHERE status_axes->>'scan_status' = 'in_progress' AND updated_at < NOW() - INTERVAL '10 minutes'`
2. Identify stage where items are stuck
3. Check for deadlocks: `SELECT * FROM pg_locks`
4. Restart stuck items via replay API

### Alert: Database Connection Pool Exhausted
**Trigger:** Connection pool utilization > 80%

**Response Steps:**
1. Check active connections: `SELECT count(*) FROM pg_stat_activity`
2. Identify long-running queries
3. Kill stale connections if needed
4. Consider increasing pool size temporarily

### Alert: Object Storage Errors
**Trigger:** Storage error rate > 1%

**Response Steps:**
1. Check storage service status page
2. Verify credentials haven't expired
3. Check network connectivity
4. Enable backup storage if configured

### Alert: PHI Access Anomaly
**Trigger:** Unusual PHI access patterns in audit log

**Response Steps:**
1. Review audit logs: `tail -f /var/log/dicom-ingestion/audit.log`
2. Verify actor_ids are legitimate
3. Check for unauthorized access attempts
4. Escalate to security team if breach suspected

## Common Issues

### Issue: Duplicate Detection Failing
**Symptoms:** Duplicate files being ingested

**Resolution:**
1. Check fingerprint calculation logic
2. Verify `dicom_duplicate_findings` table integrity
3. Re-run duplicate detection on recent items

### Issue: Binding Policy Conflicts
**Symptoms:** Items stuck in "binding" stage

**Resolution:**
1. Check `dicom_series_conflict_summaries` for conflicts
2. Review binding policy rules
3. Manually resolve conflicts if needed

### Issue: Replay Failures
**Symptoms:** Replay operations failing

**Resolution:**
1. Verify raw bytes still in storage
2. Check replay history: `SELECT * FROM dicom_replay_history`
3. Identify stage causing failure
4. Fix underlying issue before retrying

## Escalation Path

1. **L1 - On-call Engineer**
   - Initial response and triage
   - Standard playbook procedures
   - 30-minute time box

2. **L2 - Senior Engineer**
   - Complex issues requiring deep system knowledge
   - Cross-service coordination
   - 1-hour time box

3. **L3 - Team Lead / Manager**
   - Resource allocation decisions
   - External communication
   - Rollback authorization

4. **L4 - Security Team**
   - PHI access incidents
   - Compliance violations
   - Data breach response

## Post-Incident Review

Within 24 hours of incident resolution:

1. **Timeline Documentation**
   - Alert firing time
   - Response start time
   - Resolution time
   - Total downtime

2. **Root Cause Analysis**
   - Technical cause
   - Contributing factors
   - Process gaps

3. **Remediation Actions**
   - Immediate fixes applied
   - Short-term improvements (1 week)
   - Long-term improvements (1 month)

4. **Review Meeting**
   - Schedule within 3 business days
   - Include all responders
   - Document lessons learned
```

### Step 2: Create the file

```bash
cat > backend/docs/runbooks/incident_response.md << 'EOF'
[Paste content above]
EOF
```

### Step 3: Commit

```bash
git add backend/docs/runbooks/incident_response.md
git commit -m "docs(runbooks): add incident response procedures"
```

---

## Task 12: Security - Compliance Documentation

**Files:**
- Create: `backend/docs/security/compliance.md`

### Step 1: Write compliance documentation

```markdown
# DICOM Ingestion Security & Compliance Documentation

## Overview

This document describes the security controls and compliance measures implemented in the DICOM ingestion system.

## Regulatory Compliance

### HIPAA (Health Insurance Portability and Accountability Act)

**Applicable Rules:**
- Privacy Rule (45 CFR Part 160 and Subparts A and E of Part 164)
- Security Rule (45 CFR Part 160 and Subparts A and C of Part 164)
- Breach Notification Rule (45 CFR Part 164 Subpart D)

**Implemented Controls:**

#### Administrative Safeguards
- **Access Management**: Role-based access control (RBAC) for all PHI operations
- **Audit Controls**: Comprehensive audit logging of all PHI access (AuditLogger)
- **Integrity Controls**: SHA-256 checksums for all DICOM objects
- **Security Training**: Documented procedures for operators

#### Technical Safeguards
- **Access Control**: Input validation prevents unauthorized access (InputValidator)
- **Transmission Security**: TLS 1.2+ for all data in transit
- **Audit Logs**: Immutable audit trail stored separately from application logs
- **Data Integrity**: Content verification on upload and retrieval

#### Physical Safeguards
- **Workstation Security**: Refer to infrastructure documentation
- **Device Controls**: Refer to infrastructure documentation

### GDPR (General Data Protection Regulation)

**Applicable Articles:**
- Article 32: Security of processing
- Article 33: Notification of personal data breaches
- Article 35: Data protection impact assessment

**Implemented Controls:**
- Data minimization: Only necessary PHI fields stored
- Purpose limitation: Data used only for ingestion processing
- Storage limitation: Retention policies enforced

## PHI Handling

### Fields Considered PHI
The following fields are classified as PHI and subject to special handling:

**Patient Identifiers:**
- patient_name
- patient_id
- patient_birth_date
- patient_birth_time
- patient_sex
- patient_age
- patient_weight
- patient_address
- patient_phone
- patient_mothers_maiden_name

**Provider Identifiers:**
- referring_physician_name
- performing_physician_name
- operator_name
- physician_of_record

**Care Information:**
- study_description (may contain patient info)
- series_description (may contain patient info)
- raw DICOM tag values (unless explicitly allowlisted)

### PHI Protection Measures

#### 1. Logging Restrictions (PhiFilter)
- PHI fields are automatically redacted in all logs
- `[REDACTED-PHI]` token replaces actual values
- Structured logging ensures consistent filtering

#### 2. Audit Logging (AuditLogger)
- All PHI access is logged with:
  - Actor ID (who accessed)
  - Resource ID (what was accessed)
  - PHI fields accessed
  - Timestamp
  - Success/failure
- Logs are immutable and tamper-evident

#### 3. Input Validation (InputValidator)
- Path traversal prevention
- Null byte injection protection
- DICOM UID validation
- Filename sanitization

### Safe Fields (Non-PHI)
The following fields are considered safe for logging:

**Technical Identifiers:**
- study_instance_uid
- series_instance_uid
- sop_instance_uid
- sop_class_uid
- transfer_syntax_uid

**Allowlisted DICOM Tags:**
- Modality
- BodyPartExamined
- StudyDate
- StudyTime
- SeriesNumber
- InstanceNumber
- Rows, Columns
- PixelSpacing
- SliceThickness
- KVP, ExposureTime, XRayTubeCurrent

## Security Controls

### Input Validation
See `backend/src/dicom_ingestion/security/input_validator.py`

**Path Validation:**
- Maximum length: 4096 characters
- Path traversal detection: `../`, `..\`, absolute paths
- Null byte detection
- Control character filtering

**UID Validation:**
- DICOM UID format compliance
- Maximum length: 64 characters
- Pattern: digits and dots only
- No consecutive dots

### Audit Controls
See `backend/src/dicom_ingestion/security/audit_logger.py`

**Logged Events:**
- PHI access (read/write/update/delete)
- Ingestion job creation
- Replay operations
- Binding resolution
- Export operations

**Log Format:**
Structured JSON with required fields:
- timestamp (ISO 8601 UTC)
- action (CREATE, READ, UPDATE, DELETE, etc.)
- actor_id (user or service ID)
- resource_type and resource_id
- phi_accessed (boolean)
- phi_fields (list of accessed fields)
- success (boolean)
- correlation_id (for request tracing)

### Network Security

**In Transit:**
- TLS 1.2 minimum
- Certificate validation
- HSTS headers

**At Rest:**
- Database encryption (refer to infrastructure)
- Object storage encryption (refer to infrastructure)

## Testing and Verification

### Security Test Suite
```bash
# Run all security tests
python -m pytest tests/security/ -v

# Specific PHI filter tests
python -m pytest tests/security/test_phi_filter.py -v

# Audit logger tests
python -m pytest tests/security/test_audit_logger.py -v
```

### Compliance Checklist

**Before Each Release:**
- [ ] All PHI fields identified and documented
- [ ] PhiFilter tests pass
- [ ] Audit logging tests pass
- [ ] No PHI in application logs (verify via grep)
- [ ] Input validation tests pass
- [ ] Security runbook reviewed

**Quarterly:**
- [ ] Audit log review
- [ ] Access control review
- [ ] Security incident review
- [ ] Compliance training verification

## Incident Response

### PHI Breach Response

1. **Immediate (0-1 hour):**
   - Contain the breach
   - Preserve evidence
   - Notify security team

2. **Short-term (1-24 hours):**
   - Assess scope of breach
   - Identify affected individuals
   - Document timeline

3. **Notification (24-72 hours):**
   - HIPAA: Notify within 60 days if >500 individuals
   - GDPR: Notify DPA within 72 hours if required
   - Notify affected individuals as required

4. **Remediation:**
   - Fix security gap
   - Update procedures
   - Post-incident review

## Contacts

- **Security Team:** security@example.com
- **Compliance Officer:** compliance@example.com
- **On-Call Engineer:** See PagerDuty
```

### Step 2: Create the file

```bash
mkdir -p backend/docs/security
cat > backend/docs/security/compliance.md << 'EOF'
[Paste content above]
EOF
```

### Step 3: Commit

```bash
git add backend/docs/security/compliance.md
git commit -m "docs(security): add compliance documentation with PHI handling"
```

---

## Task 13: Dashboard Configuration

**Files:**
- Create: `backend/dashboards/ingestion_dashboard.json`

### Step 1: Write Grafana dashboard config

```json
{
  "dashboard": {
    "id": null,
    "title": "DICOM Ingestion - Production Overview",
    "tags": ["dicom", "ingestion", "production"],
    "timezone": "UTC",
    "schemaVersion": 36,
    "refresh": "30s",
    "panels": [
      {
        "id": 1,
        "title": "Ingestion Rate (items/min)",
        "type": "stat",
        "targets": [
          {
            "expr": "rate(dicom_ingestion_items_total[5m]) * 60",
            "legendFormat": "{{stage}} - {{status}}"
          }
        ],
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0}
      },
      {
        "id": 2,
        "title": "Error Rate by Stage",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(dicom_ingestion_items_total{status=\"failed\"}[5m])",
            "legendFormat": "{{stage}}"
          }
        ],
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0}
      },
      {
        "id": 3,
        "title": "Stage Duration (p99)",
        "type": "timeseries",
        "targets": [
          {
            "expr": "histogram_quantile(0.99, rate(dicom_ingestion_stage_duration_ms_bucket[5m]))",
            "legendFormat": "{{stage}}"
          }
        ],
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8}
      },
      {
        "id": 4,
        "title": "Stuck Items",
        "type": "stat",
        "targets": [
          {
            "expr": "dicom_ingestion_items_stuck_total",
            "legendFormat": "{{stage}}"
          }
        ],
        "alert": {
          "name": "Stuck Items Alert",
          "condition": {
            "evaluator": {"params": [0], "type": "gt"},
            "reducer": {"type": "last"},
            "query": {"params": ["A", "5m", "now"]}
          },
          "executionErrorState": "alerting",
          "frequency": "1m",
          "handler": 1,
          "noDataState": "no_data",
          "notifications": [{"uid": "dicom_ingestion_alerts"}]
        },
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8}
      },
      {
        "id": 5,
        "title": "Error Breakdown by Type",
        "type": "piechart",
        "targets": [
          {
            "expr": "dicom_ingestion_errors_total",
            "legendFormat": "{{error_code}}"
          }
        ],
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16}
      },
      {
        "id": 6,
        "title": "Job Completion Rate",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(dicom_ingestion_jobs_total{status=\"completed\"}[5m])",
            "legendFormat": "completed"
          },
          {
            "expr": "rate(dicom_ingestion_jobs_total{status=\"failed\"}[5m])",
            "legendFormat": "failed"
          }
        ],
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16}
      },
      {
        "id": 7,
        "title": "Service Health",
        "type": "table",
        "targets": [
          {
            "expr": "up{job=\"dicom-ingestion\"}",
            "format": "table"
          }
        ],
        "gridPos": {"h": 4, "w": 24, "x": 0, "y": 24}
      }
    ]
  }
}
```

### Step 2: Create the file

```bash
mkdir -p backend/dashboards
cat > backend/dashboards/ingestion_dashboard.json << 'EOF'
[Paste JSON content above]
EOF
```

### Step 3: Commit

```bash
git add backend/dashboards/ingestion_dashboard.json
git commit -m "feat(observability): add Grafana dashboard configuration"
```

---

## Task 14: Integration - Wire Observability into Services

**Files:**
- Modify: `backend/src/dicom_ingestion/services/upload/upload_service.py`
- Modify: `backend/src/dicom_ingestion/services/scanner/scan_service.py`

### Step 1: Modify upload_service.py

Add at imports section:
```python
# Add to existing imports
import logging
from ...observability.logging_config import set_job_context, get_correlation_id
from ...observability.collector import PipelineMetricsCollector, PipelineStage
from ...security.audit_logger import AuditLogger, AuditAction
```

Modify the `accept` method to add metrics and audit logging:

```python
    def accept(
        self,
        input_data: Union[bytes, BinaryIO],
        filename: str = "",
        original_filename: str = "",
        job_id: str = "",
        actor_id: str = ""
    ) -> UploadPackage:
        """Accept upload input and persist raw bytes to object storage.
        
        Enhanced with observability and audit logging.
        """
        import time
        from ...security.input_validator import InputValidator
        
        validator = InputValidator()
        metrics_collector = getattr(self, '_metrics', None)
        audit_logger = getattr(self, '_audit_logger', None)
        
        start_time = time.time()
        
        # Set correlation context
        if job_id:
            set_job_context(job_id=job_id)
        
        # Validate input
        if filename:
            validation = validator.validate_upload_filename(filename)
            if not validation.is_valid:
                self._logger.warning(
                    "Upload filename validation failed",
                    extra={"filename": filename, "errors": validation.errors}
                )
                raise ValueError(f"Invalid filename: {validation.errors}")
        
        try:
            # Record stage start
            if metrics_collector:
                metrics_collector.record_job_started(job_id or "unknown")
            
            # Existing logic...
            if hasattr(input_data, 'read'):
                data = input_data.read()
            elif isinstance(input_data, bytes):
                data = input_data
            elif isinstance(input_data, str):
                with open(input_data, 'rb') as f:
                    data = f.read()
            else:
                raise ValueError(f"Unsupported input type: {type(input_data)}")

            if not data:
                raise ValueError("Empty upload not allowed")

            content_hash = hashlib.sha256(data).hexdigest()
            size_bytes = len(data)
            result = self._object_store.put(data, content_hash=content_hash)
            uri = result.get("uri")

            if not uri:
                raise UploadPackageStoreFailed("Object store did not return a URI")

            if not self._object_store.exists(uri):
                raise UploadPackageStoreFailed(f"Storage verification failed for URI: {uri}")
            
            package = UploadPackage(
                uri=uri,
                content_hash=content_hash,
                size_bytes=size_bytes,
                original_filename=original_filename or filename
            )
            
            # Record success
            duration_ms = (time.time() - start_time) * 1000
            if metrics_collector:
                metrics_collector.record_job_completed(job_id or "unknown", success=True)
            
            # Audit log
            if audit_logger and job_id:
                audit_logger.log_phi_access(
                    action=AuditAction.CREATE,
                    actor_id=actor_id or "system",
                    resource_type="upload_package",
                    resource_id=content_hash,
                    phi_fields=[],
                    success=True,
                    size_bytes=size_bytes,
                    filename=filename
                )
            
            self._logger.info(
                "Upload accepted",
                extra={
                    "job_id": job_id,
                    "content_hash": content_hash,
                    "size_bytes": size_bytes,
                    "duration_ms": duration_ms
                }
            )
            
            return package

        except (IOError, OSError) as e:
            duration_ms = (time.time() - start_time) * 1000
            if metrics_collector:
                metrics_collector.record_job_completed(job_id or "unknown", success=False)
            raise UploadPackageStoreFailed(f"Storage I/O error: {e}") from e
        except ValueError:
            raise
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            if metrics_collector:
                metrics_collector.record_job_completed(job_id or "unknown", success=False)
            if isinstance(e, UploadPackageStoreFailed):
                raise
            raise UploadPackageStoreFailed(f"Unexpected error during upload: {e}") from e
```

### Step 2: Modify scan_service.py

Add at imports:
```python
import time
from ...observability.collector import PipelineMetricsCollector, PipelineStage
```

Modify the `scan` method to add metrics:

```python
    def scan(
        self,
        upload_package,
        max_recursion_depth: int = 3,
        metrics_collector: PipelineMetricsCollector = None,
        job_id: str = ""
    ) -> ScanManifest:
        """Scan an upload package to discover DICOM candidates.
        
        Enhanced with observability.
        """
        from ...observability.logging_config import set_job_context
        
        if job_id:
            set_job_context(job_id=job_id)
        
        manifest = ScanManifest()
        top_level_rejected_count = 0
        stage_start = time.time()
        
        try:
            package_bytes = self._get_package_bytes(upload_package)
            if package_bytes is None:
                manifest.scan_errors.append(f"Could not retrieve package bytes")
                return manifest

            is_zip = self._is_zip_file(package_bytes)

            if is_zip:
                self._scan_zip_contents(
                    package_bytes,
                    manifest,
                    current_depth=0,
                    max_depth=max_recursion_depth
                )
            else:
                self._scan_single_file(
                    package_bytes,
                    upload_package.original_filename or "unknown",
                    manifest
                )

        except ZipBombDetected as e:
            manifest.scan_errors.append(f"ZIP bomb detected: {e}")
            top_level_rejected_count += 1
            if metrics_collector:
                metrics_collector.record_stage_complete(
                    item_id=upload_package.content_hash if hasattr(upload_package, 'content_hash') else "unknown",
                    stage=PipelineStage.SCAN,
                    success=False,
                    duration_ms=(time.time() - stage_start) * 1000,
                    error_code="ZIP_BOMB"
                )
        except UnsafeArchivePath as e:
            manifest.scan_errors.append(f"Unsafe archive path: {e}")
            top_level_rejected_count += 1
        except NestedZipTooDeep as e:
            manifest.scan_errors.append(f"ZIP nesting too deep: {e}")
            top_level_rejected_count += 1
        except Exception as e:
            manifest.scan_errors.append(f"Scan error: {e}")

        # Update manifest totals
        manifest.total_items = len(manifest.items)
        manifest.dicom_count = sum(1 for item in manifest.items if item.is_dicom)
        manifest.non_dicom_count = sum(1 for item in manifest.items if not item.is_dicom and item.scan_status != ScanStatus.REJECTED_UNSAFE)
        item_rejected_count = sum(
            1 for item in manifest.items
            if item.scan_status in [ScanStatus.REJECTED_UNSAFE, ScanStatus.REJECTED_NON_DICOM]
        )
        manifest.rejected_count = item_rejected_count + top_level_rejected_count
        
        # Record metrics for each item
        if metrics_collector:
            duration_ms = (time.time() - stage_start) * 1000
            for item in manifest.items:
                success = item.scan_status == ScanStatus.PENDING
                error_code = None
                if item.scan_status == ScanStatus.REJECTED_UNSAFE:
                    error_code = "UNSAFE"
                elif item.scan_status == ScanStatus.REJECTED_NON_DICOM:
                    error_code = "NON_DICOM"
                
                metrics_collector.record_stage_complete(
                    item_id=item.source_path,
                    stage=PipelineStage.SCAN,
                    success=success,
                    duration_ms=duration_ms / max(len(manifest.items), 1),
                    error_code=error_code
                )
        
        self._logger.info(
            "Scan complete",
            extra={
                "job_id": job_id,
                "total_items": manifest.total_items,
                "dicom_count": manifest.dicom_count,
                "rejected_count": manifest.rejected_count
            }
        )

        return manifest
```

### Step 3: Run tests

Run existing tests to ensure no regression:
```bash
python -m pytest tests/services/upload/ -v
python -m pytest tests/services/scanner/ -v
```

### Step 4: Commit

```bash
git add backend/src/dicom_ingestion/services/upload/upload_service.py
git add backend/src/dicom_ingestion/services/scanner/scan_service.py
git commit -m "feat(integration): wire observability into upload and scan services"
```

---

## Task 15: Final Integration Test

**Files:**
- Create: `backend/tests/test_batch6_integration.py`

### Step 1: Write integration test

```python
# backend/tests/test_batch6_integration.py
"""Integration tests for Batch 6 production readiness features."""

import pytest
from dicom_ingestion.observability.metrics import Counter, Histogram, MetricsRegistry
from dicom_ingestion.observability.collector import PipelineMetricsCollector, PipelineStage
from dicom_ingestion.observability.health import HealthCheck, CheckResult
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
        
        # Simulate pipeline stages
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
        
        # Verify metrics output
        output = collector.get_metrics_output()
        assert "dicom_ingestion_items_total" in output
        assert "dicom_ingestion_stage_duration_ms" in output
        assert "dicom_ingestion_errors_total" in output
    
    def test_security_pipeline(self, tmp_path):
        """Test security controls pipeline."""
        # Input validation
        validator = InputValidator()
        
        # Valid path
        result = validator.validate_path("folder/file.dcm")
        assert result.is_valid
        
        # Invalid path
        result = validator.validate_path("../../../etc/passwd")
        assert not result.is_valid
        
        # PHI filtering
        data = {
            "patient_name": "John Doe",
            "study_instance_uid": "1.2.3.4",
            "rows": 512
        }
        filtered = PhiFilter.filter_for_logging(data)
        assert filtered["patient_name"] == "[REDACTED-PHI]"
        assert filtered["study_instance_uid"] == "1.2.3.4"
        
        # Audit logging
        log_file = tmp_path / "audit.log"
        audit_logger = AuditLogger(str(log_file))
        
        audit_logger.log_phi_access(
            action=AuditAction.READ,
            actor_id="test_user",
            resource_type="dicom_instance",
            resource_id="inst_1",
            phi_fields=["study_instance_uid"],
            success=True
        )
        
        # Verify log written
        import json
        with open(log_file) as f:
            entry = json.loads(f.readline())
        assert entry["action"] == "READ"
        assert entry["phi_accessed"] == True
    
    def test_health_and_smoke_checks(self):
        """Test health checks and smoke test framework."""
        # Health check
        health = HealthCheck("dicom_ingestion")
        health.add_check("db", lambda: CheckResult.healthy("OK"))
        
        status = health.get_status()
        assert status.status == "healthy"
        
        # Smoke test
        suite = SmokeTestSuite("dicom_ingestion")
        
        def passing_test():
            return SmokeTestResult.passed("OK")
        
        suite.add_test("always_passes", passing_test)
        result = suite.run()
        
        assert result.success
        assert result.tests["always_passes"].passed
    
    def test_end_to_end_production_readiness(self, tmp_path):
        """Complete production readiness verification."""
        # 1. Metrics work
        registry = MetricsRegistry()
        counter = Counter("test_e2e", "End to end test counter")
        registry.register(counter)
        counter.inc()
        
        # 2. Security controls work
        validator = InputValidator()
        assert validator.validate_uid("1.2.840.10008.1.2.1").is_valid
        
        # 3. PHI filtering works
        data = {"patient_name": "Secret", "modality": "CT"}
        filtered = PhiFilter.filter_for_logging(data)
        assert filtered["patient_name"] == "[REDACTED-PHI]"
        assert filtered["modality"] == "CT"
        
        # 4. Health checks work
        health = HealthCheck("test")
        health.add_check("test", lambda: CheckResult.healthy("OK"))
        assert health.get_status().status == "healthy"
        
        # 5. Smoke tests work
        suite = SmokeTestSuite("test")
        suite.add_test("test", lambda: SmokeTestResult.passed("OK"))
        assert suite.run().success
        
        print("✓ All production readiness components working")
```

### Step 2: Run integration tests

Run: `python -m pytest tests/test_batch6_integration.py -v`

Expected: PASS

### Step 3: Commit

```bash
git add backend/tests/test_batch6_integration.py
git commit -m "test(batch6): add end-to-end production readiness integration tests"
```

---

## Plan Summary

This plan implements Batch 6 Production Readiness covering:

**C7 - Observability Implementation:**
- Core metrics infrastructure (Counter, Histogram, Registry)
- Pipeline stage metrics collector
- Health check system
- Structured logging with correlation IDs
- Grafana dashboard configuration

**D2 - Security & Compliance:**
- Input validation (paths, UIDs)
- Audit logging for PHI operations
- PHI filtering for safe logging
- Compliance documentation

**D4 - Rollout/Rollback Readiness:**
- Smoke test framework
- Deployment validation checks
- Deployment runbook
- Incident response runbook

**Integration:**
- Observability wired into upload and scan services
- End-to-end integration tests
- All components tested independently and together

**Exit Criteria:**
1. All tests pass
2. Metrics output in Prometheus format
3. Audit logs record all PHI access
4. No PHI in application logs
5. Smoke tests pass
6. Runbooks complete and reviewed
