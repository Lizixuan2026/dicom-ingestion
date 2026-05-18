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

        # Counter for active jobs
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
        """Record the start of a stage for an item."""
        pass  # Simplified for now

    def record_stage_complete(
        self,
        item_id: str,
        stage: PipelineStage,
        success: bool,
        duration_ms: float,
        error_code: Optional[str] = None
    ) -> None:
        """Record stage completion."""
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
