"""What a metric is judged against. A metric without one is just a number."""
from __future__ import annotations

from . import registry
from .schemas import Dimension, Metric, Reference, ReferenceKind, Slice, Window

MIN_PEERS = 3          # a median over two values is not a peer comparison
TREND_WINDOWS = 4


def resolve(con, metric: Metric, slc: Slice, window: Window) -> tuple[Reference, ...]:
    """Every declared reference that can actually be computed, in declaration
    order. One that cannot is OMITTED, never faked."""
    out: list[Reference] = []
    for kind in metric.refs:
        if kind is ReferenceKind.TREND:
            r = _trend(con, metric, slc, window)
        elif kind is ReferenceKind.TARGET:
            r = Reference(ReferenceKind.TARGET, metric.target, "SLA target")
        else:
            r = _peer(con, metric, slc, window)
        if r is not None:
            out.append(r)
    return tuple(out)


def _trend(con, metric, slc, window) -> Reference | None:
    """Mean of the metric over the four COMPLETE PRECEDING windows, excluding the
    one under evaluation. Averaging only the windows that returned a value means
    one missing week degrades the reference rather than voiding it."""
    values = [v for v in (registry.evaluate(con, metric, slc, window.shifted_back(b))
                          for b in range(1, TREND_WINDOWS + 1)) if v is not None]
    if not values:
        return None
    return Reference(ReferenceKind.TREND, sum(values) / len(values), "4-week average")


def _peer(con, metric, slc, window) -> Reference | None:
    if slc.dim is Dimension.NONE:
        return None
    peers = [v for other in registry.distinct_values(con, slc.dim, window)
             if other != slc.value                      # the subject is not its own peer
             for v in [registry.evaluate(con, metric, Slice(slc.dim, other), window)]
             if v is not None]
    if len(peers) < MIN_PEERS:
        return None
    peers.sort()
    mid = len(peers) // 2
    median = peers[mid] if len(peers) % 2 else (peers[mid - 1] + peers[mid]) / 2
    return Reference(ReferenceKind.PEER, median, "peer median")
