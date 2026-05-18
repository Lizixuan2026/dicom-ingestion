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

    def get_value(self, labels: Optional[Dict[str, str]] = None) -> int:
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
            lines.append(f"{self.name} {self.get_value()}")
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
