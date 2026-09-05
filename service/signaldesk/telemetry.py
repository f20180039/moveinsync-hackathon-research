"""Query, sweep and model latency -- measured rather than asserted.

Criterion 2 names three things by name: inference cost per interaction,
LATENCY, and efficiency at enterprise volumes. Cost has been measured since
model.py's CostMeter; latency was a claim in a README. The DuckDB choice was
itself justified ON latency -- sub-millisecond in-process against Athena's
~2s floor per query -- so leaving it unmeasured leaves the load-bearing
architectural argument unevidenced.

Three call sites, not everywhere: registry.evaluate ("metric_query"),
sweep.sweep ("sweep"), and SarvamClient.complete / complete_message
("model_call"). A profiler is not the goal; answering criterion 2 is.
"""
from __future__ import annotations

import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class LatencyMeter:
    samples: dict[str, list[float]] = field(default_factory=dict)

    @contextmanager
    def measure(self, label: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            # `finally`, deliberately: if an exception skipped the record,
            # p95 would silently exclude every slow FAILING call, which is
            # precisely the population worth knowing about.
            self.samples.setdefault(label, []).append(
                (time.perf_counter() - t0) * 1000.0)

    def stats(self, label: str) -> dict | None:
        """None -- never a zero -- for a label nobody measured. A zero on the
        console reads as "instant", which is the opposite of "unknown"."""
        xs = sorted(self.samples.get(label, []))
        if not xs:
            return None
        return {
            "n": len(xs),
            "p50Ms": round(statistics.median(xs), 3),
            # Index, not interpolation: with n < 20 an interpolated p95
            # invents a value between two real samples. Report a real
            # observation.
            "p95Ms": round(xs[min(len(xs) - 1, int(len(xs) * 0.95))], 3),
            "maxMs": round(xs[-1], 3),
        }

    def snapshot(self) -> dict:
        return {k: v for k, v in
                ((label, self.stats(label)) for label in self.samples) if v}

    def reset(self) -> None:
        self.samples.clear()


LATENCY = LatencyMeter()
