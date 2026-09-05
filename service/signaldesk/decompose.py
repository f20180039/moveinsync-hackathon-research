"""Root-cause gap decomposition (Task 8, Capability 3 of Amendment 1.1).

Turns "OTA is 7 points below trend" into "4.1 of those points are driver
delay, concentrated in two vendors" -- pure arithmetic over registry.py's own
(value, n) pairs. This module contains no SQL of its own; every number here
traces back to registry.evaluate_with_n or registry.delay_reason_breakdown
(spec 1.1: SELECT only in registry.py and ingest.py).

Two decompositions:

  * By an enumerated Dimension (VENDOR, SITE, ...): each value's share of the
    finding's own population, and how many points of the finding's gap that
    value owns.
  * By DELAY_REASON: MoveInSync's own delay taxonomy (TRAFFIC/DRIVER/EMPLOYEE
    -- docs/moveinsync-domain-vocabulary.md SS1, docs/real-dataset-mapping.md
    SS4), which only means something for an on-time metric (there is no
    "late trip" to attribute for cost_per_km or no_show_rate).

The reference point a dimension decomposition compares each value against is
derived algebraically from the finding itself rather than re-deriving which
Reference "fired" (verdict.py already folds a LOW_CONFIDENCE cause over the
original firing reference, and recovering it independently would duplicate
that logic): for a HIGHER-is-better metric, finding.gap ~= reference -
overall_observed (verdict.delta's own definition, unsaturated case), so
reference = overall_observed + finding.gap; for a LOWER-is-better metric,
reference = overall_observed - finding.gap. A value's own contribution is then
its share of the population times how far ITS observed value sits from that
same reference, signed so positive always means "this value made it worse" --
the same convention Finding.gap itself uses (deviation 1).

Summed over a dimension that exactly partitions the population, this
telescopes to precisely finding.gap for a metric whose SQL is a simple
count-weighted ratio (ota/otd/vendor_ota): the weighted average of every
value's own observed rate, weighted by that value's own row count, is
mathematically the overall rate. no_show_rate's declared population column is
trip count while its ratio's true denominator is planned-employee count
(registry.py's own comment on that metric), so its sum is an approximation,
not an identity -- which is why the sum-to-whole test carries a tolerance
rather than asserting exact equality throughout.

A dimension value below MIN_ROWS_PER_SLICE is not silently dropped (that
would understate the population the sum is taken over) -- it, and any value
present in the window but never returned as its own metric row (a null
dimension value, or one this metric's own required columns exclude), is
folded into one "(other)" row so the reported population, and therefore the
sum of points_of_gap, never quietly shrinks.
"""
from __future__ import annotations

from typing import Literal

from . import constants as C
from . import registry
from .schemas import Dimension, Direction, Finding, Slice, Window

DELAY_REASON = "DELAY_REASON"

# Only the metrics built on registry's on-time SQL carry a delay-reason
# breakdown that means anything -- decomposing e.g. cost_per_km by delay
# reason would answer a question nobody asked.
ON_TIME_METRIC_IDS = ("ota", "otd", "vendor_ota")

OTHER = "(other)"

_VALID_DIMS = tuple(d.name for d in Dimension if d is not Dimension.NONE) + (DELAY_REASON,)


def valid_dims() -> str:
    """For a 422 message that names every valid value, dimension or not."""
    return ", ".join(_VALID_DIMS)


def _is_delay_reason(dim) -> bool:
    return isinstance(dim, str) and dim.upper() == DELAY_REASON


def _shortfall(observed: float, reference: float, better: Direction) -> float:
    """Points of shortfall against `reference`, signed so positive always
    means worse -- the same convention Finding.gap uses (deviation 1)."""
    return (reference - observed) if better is Direction.HIGHER else (observed - reference)


def _reference_point(finding: Finding, better: Direction, overall_observed: float) -> float:
    """The reference-equivalent point implied by the finding's own gap (see
    the module docstring's algebra)."""
    return overall_observed + finding.gap if better is Direction.HIGHER else overall_observed - finding.gap


def _decompose_dimension(con, finding: Finding, dim: Dimension) -> list[dict]:
    metric = registry.by_id(finding.metric_id)
    parent = () if finding.slice.dim is Dimension.NONE else (finding.slice,)

    overall_observed, overall_n = registry.evaluate_with_n(con, metric, finding.slice, finding.window)
    if overall_observed is None or overall_n <= 0:
        return []

    reference = _reference_point(finding, metric.better, overall_observed)

    rows: list[dict] = []
    counted_n = 0
    thin_n = 0
    for value in registry.distinct_values(con, dim, finding.window):
        slc = parent + (Slice(dim, value),)
        value_observed, n = registry.evaluate_with_n(con, metric, slc, finding.window)
        if n <= 0:
            continue
        counted_n += n
        if n < C.MIN_ROWS_PER_SLICE or value_observed is None:
            thin_n += n
            continue
        share = n / overall_n
        rows.append({
            "value": value,
            "observed": value_observed,
            "share_of_volume": share,
            "points_of_gap": share * _shortfall(value_observed, reference, metric.better),
            "n": n,
        })

    # Any volume this metric counts overall but that never showed up as its
    # own trusted row -- a thin slice, or a null/excluded dimension value --
    # is folded into one "(other)" row so the sum is taken over the WHOLE
    # population the finding itself was measured over, not just the part that
    # happened to clear the population floor.
    other_n = thin_n + max(overall_n - counted_n, 0)
    if other_n > 0:
        rows.append({
            "value": OTHER,
            "observed": None,
            "share_of_volume": other_n / overall_n,
            "points_of_gap": finding.gap - sum(r["points_of_gap"] for r in rows),
            "n": other_n,
        })

    rows.sort(key=lambda r: -r["points_of_gap"])
    return rows


def _decompose_delay_reason(con, finding: Finding) -> list[dict]:
    if finding.metric_id not in ON_TIME_METRIC_IDS:
        # Documented reason (Task 8 controller ruling): this decomposition
        # answers "which delay bucket owns the late trips", which only
        # applies to a metric that is itself an on-time rate.
        return []

    parent = () if finding.slice.dim is Dimension.NONE else (finding.slice,)
    breakdown = registry.delay_reason_breakdown(con, parent, finding.window)
    total_late = sum(n for _, n, _ in breakdown)
    if total_late <= 0:
        return []

    # shortfall = the finding's own gap, in points -- share x shortfall per
    # reason then sums to exactly the finding's gap (docs/real-dataset-
    # mapping.md SS4's own worked example), no reference derivation needed:
    # unlike a dimension decomposition, a delay reason has no "observed rate
    # of its own" to compare against a reference -- only a share of the late
    # trips the finding's own gap already accounts for.
    shortfall = finding.gap

    rows: list[dict] = []
    thin_n = 0
    for reason, n, avg_delay_min in breakdown:
        if n < C.MIN_ROWS_PER_SLICE:
            thin_n += n
            continue
        share = n / total_late
        rows.append({
            "value": reason,
            "observed": avg_delay_min,
            "share_of_volume": share,
            "points_of_gap": share * shortfall,
            "n": n,
        })

    if thin_n > 0:
        rows.append({
            "value": OTHER,
            "observed": None,
            "share_of_volume": thin_n / total_late,
            "points_of_gap": shortfall - sum(r["points_of_gap"] for r in rows),
            "n": thin_n,
        })

    rows.sort(key=lambda r: -r["points_of_gap"])
    return rows


def decompose(con, finding: Finding, dim: "Dimension | Literal['DELAY_REASON']") -> list[dict]:
    """Attribute a finding's shortfall across one dimension.

    Returns, per dimension value: observed, share_of_volume, points_of_gap
    (how much of the finding's own gap this value owns, signed so positive
    means worse) and n. Sorted worst first. `dim` is either a schemas.Dimension
    member or the literal string "DELAY_REASON".
    """
    if _is_delay_reason(dim):
        return _decompose_delay_reason(con, finding)
    if not isinstance(dim, Dimension):
        try:
            dim = Dimension.parse(dim)
        except ValueError:
            raise ValueError(f"unknown dimension {dim!r}; valid values are {valid_dims()}")
    if dim is Dimension.NONE:
        raise ValueError(f"dimension NONE cannot be decomposed; valid values are {valid_dims()}")
    return _decompose_dimension(con, finding, dim)
