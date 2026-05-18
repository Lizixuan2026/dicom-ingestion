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
