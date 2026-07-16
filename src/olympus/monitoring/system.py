"""Host system metrics, measured via the standard library (psutil optional).

Reports only values that can be genuinely measured in this environment:
- disk usage via :func:`shutil.disk_usage` (always available),
- process CPU seconds and peak RSS via :mod:`resource` (POSIX),
- CPU count and load averages via :mod:`os`.
If ``psutil`` is installed it is used to enrich system-wide memory; otherwise
those fields are reported as ``None`` (UNKNOWN) and listed in ``unavailable`` -
never fabricated.
"""

from __future__ import annotations

import os
import shutil
from importlib import import_module

from olympus.domain.entities.monitoring import SystemMetrics


def collect_system_metrics(disk_path: str = ".") -> SystemMetrics:
    """Collect real host metrics; unmeasurable fields stay ``None``."""

    metrics = SystemMetrics()
    unavailable: list[str] = []

    metrics.cpu_count = os.cpu_count()

    # Load average (POSIX only).
    getloadavg = getattr(os, "getloadavg", None)
    if getloadavg is not None:
        try:
            one, five, fifteen = getloadavg()
            metrics.load_avg_1m, metrics.load_avg_5m, metrics.load_avg_15m = (
                round(one, 2),
                round(five, 2),
                round(fifteen, 2),
            )
        except OSError:
            unavailable.append("load_average")
    else:
        unavailable.append("load_average")

    # Process CPU time + peak RSS (POSIX).
    try:
        resource = import_module("resource")

        usage = resource.getrusage(resource.RUSAGE_SELF)
        metrics.process_cpu_seconds = round(usage.ru_utime + usage.ru_stime, 3)
        # ru_maxrss is kilobytes on Linux.
        metrics.process_max_rss_bytes = int(usage.ru_maxrss) * 1024
    except (ImportError, AttributeError, ValueError):
        unavailable.append("process_resource_usage")

    # Disk usage (always available).
    try:
        disk = shutil.disk_usage(disk_path)
        metrics.disk_total_bytes = disk.total
        metrics.disk_used_bytes = disk.used
        metrics.disk_free_bytes = disk.free
    except OSError:
        unavailable.append("disk_usage")

    # System-wide memory (psutil only).
    try:
        import psutil

        vm = psutil.virtual_memory()
        metrics.system_memory_total_bytes = vm.total
        metrics.system_memory_available_bytes = vm.available
        metrics.source = "psutil"
    except Exception:
        unavailable.append("system_memory")

    metrics.unavailable = unavailable
    return metrics
