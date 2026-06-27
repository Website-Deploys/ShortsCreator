"""Operational cost *estimation* from measured work (never billing).

Cost is computed from quantities Olympus actually measured - transcription
minutes (analysed video duration), render minutes (measured render-stage time),
storage bytes (measured), and process CPU seconds (measured). Quantities that are
not instrumented (LLM tokens, GPU time) are reported as UNKNOWN with a zero
contribution and a clear note. Rates are configurable constants; the output is
always labelled an estimate.
"""

from __future__ import annotations

from olympus.domain.entities.monitoring import CostEstimate, CostLine

# Configurable indicative rates (USD). These are placeholders for estimation, not
# a price list - a deployment overrides them with its real contracted rates.
RATE_TRANSCRIPTION_PER_MIN = 0.006
RATE_RENDER_PER_MIN = 0.05
RATE_STORAGE_PER_GB_MONTH = 0.02
RATE_CPU_PER_HOUR = 0.04
RATE_LLM_PER_1K_TOKENS = 0.002
RATE_GPU_PER_HOUR = 0.60


def build_cost_estimate(
    *,
    transcription_minutes: float | None,
    render_minutes: float | None,
    storage_bytes: int | None,
    cpu_seconds: float | None,
    llm_tokens: int | None = None,
    gpu_seconds: float | None = None,
) -> CostEstimate:
    """Build a cost estimate from measured quantities (UNKNOWN where not measured)."""

    estimate = CostEstimate()

    def line(item: str, qty: float | None, unit: str, rate: float, note: str = "") -> None:
        cost = round(qty * rate, 4) if qty is not None else None
        estimate.lines.append(
            CostLine(
                item=item, quantity=qty, unit=unit, rate_usd=rate, estimated_usd=cost, note=note
            )
        )
        if cost is not None:
            estimate.total_usd += cost

    line(
        "transcription",
        transcription_minutes,
        "minutes",
        RATE_TRANSCRIPTION_PER_MIN,
        "measured from analysed video duration",
    )
    line(
        "render",
        render_minutes,
        "minutes",
        RATE_RENDER_PER_MIN,
        "measured from render-stage wall-clock time",
    )
    gb = round(storage_bytes / (1024**3), 4) if storage_bytes is not None else None
    line(
        "storage",
        gb,
        "GB-month",
        RATE_STORAGE_PER_GB_MONTH,
        "measured current storage; estimated for one month",
    )
    cpu_hours = round(cpu_seconds / 3600.0, 4) if cpu_seconds is not None else None
    line("cpu", cpu_hours, "cpu-hours", RATE_CPU_PER_HOUR, "measured process CPU time")
    line(
        "llm_tokens",
        (llm_tokens / 1000.0) if llm_tokens else None,
        "1k-tokens",
        RATE_LLM_PER_1K_TOKENS,
        "UNKNOWN - token usage is not instrumented",
    )
    line(
        "gpu",
        (gpu_seconds / 3600.0) if gpu_seconds else None,
        "gpu-hours",
        RATE_GPU_PER_HOUR,
        "UNKNOWN - GPU time is not instrumented (future-ready)",
    )
    return estimate
