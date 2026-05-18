"""Observability module for DICOM ingestion."""
from .metrics import Counter, Histogram, MetricsRegistry
from .collector import PipelineMetricsCollector, PipelineStage
from .health import HealthCheck, HealthStatus, CheckResult, ServiceStatus
from .logging_config import (
    StructuredLogFormatter,
    CorrelationIdFilter,
    set_correlation_id,
    get_correlation_id,
    set_job_context,
    get_job_context,
    configure_logging,
)

__all__ = [
    "Counter",
    "Histogram",
    "MetricsRegistry",
    "PipelineMetricsCollector",
    "PipelineStage",
    "HealthCheck",
    "HealthStatus",
    "CheckResult",
    "ServiceStatus",
    "StructuredLogFormatter",
    "CorrelationIdFilter",
    "set_correlation_id",
    "get_correlation_id",
    "set_job_context",
    "get_job_context",
    "configure_logging",
]
