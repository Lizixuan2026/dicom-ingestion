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
    - Replay operations
    - Conflict resolution
    - Indexing lag
    - Recovery metrics
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

        # Counter for replay operations (dashboard panel: Replay Operations)
        self.replay_counter = Counter(
            "dicom_ingestion_replay_total",
            "Total replay operations",
            labels=["status"]  # success, failed
        )
        self.registry.register(self.replay_counter)

        # Counter for conflict resolution (dashboard panel: Conflict Resolution Status)
        self.conflict_counter = Counter(
            "dicom_ingestion_conflict_total",
            "Total binding policy conflicts",
            labels=["resolution_status"]  # auto_resolved, manual_intervention, pending
        )
        self.registry.register(self.conflict_counter)

        # Histogram for indexing lag (dashboard panel: Indexing Lag)
        self.index_lag_histogram = Histogram(
            "dicom_ingestion_index_lag_seconds",
            "Time lag between data persistence and search indexing",
            buckets=[1, 5, 10, 30, 60, 120, 300, 600]
        )
        self.registry.register(self.index_lag_histogram)

        # Histogram for recovery duration (dashboard panel: Recovery Time)
        self.recovery_histogram = Histogram(
            "dicom_ingestion_recovery_duration_ms",
            "Duration of replay-based recovery operations",
            buckets=[100, 500, 1000, 2500, 5000, 10000, 30000, 60000]
        )
        self.registry.register(self.recovery_histogram)

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

    def record_replay(self, success: bool) -> None:
        """Record a replay operation.
        
        Used by dashboard: Replay Operations panel
        """
        status = "success" if success else "failed"
        self.replay_counter.inc(labels={"status": status})

    def record_conflict_resolution(self, resolution_status: str) -> None:
        """Record a conflict resolution event.
        
        Args:
            resolution_status: One of "auto_resolved", "manual_intervention", "pending"
        
        Used by dashboard: Conflict Resolution Status panel
        """
        self.conflict_counter.inc(labels={"resolution_status": resolution_status})

    def record_index_lag(self, lag_seconds: float) -> None:
        """Record indexing lag.
        
        Args:
            lag_seconds: Time between data persistence and indexing
        
        Used by dashboard: Indexing Lag panel
        """
        self.index_lag_histogram.observe(lag_seconds)

    def record_recovery(self, duration_ms: float) -> None:
        """Record a recovery operation duration.
        
        Args:
            duration_ms: Duration of recovery operation in milliseconds
        
        Used by dashboard: Recovery Time (MTTR) panel
        """
        self.recovery_histogram.observe(duration_ms)

    def get_metrics_output(self) -> str:
        """Get all metrics in Prometheus format."""
        return self.registry.output_prometheus_format()
