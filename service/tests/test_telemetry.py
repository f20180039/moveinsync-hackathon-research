"""Latency is measured, not asserted.

Criterion 2 names "inference cost per interaction, latency, efficiency at
enterprise volumes". Cost was measured; latency was a claim. These tests pin
the meter that turns it into evidence.
"""
from __future__ import annotations

import datetime as dt
import pathlib

import duckdb
import pytest

from signaldesk import ingest, registry, sweep
from signaldesk.schemas import Slice, Window
from signaldesk.telemetry import LATENCY, LatencyMeter

SAMPLE = str(pathlib.Path(__file__).resolve().parents[2] / "data" / "sample")
WINDOW = Window(0, 2_000_000_000_000)
CLOCK_MS = int(dt.datetime(2026, 8, 1, tzinfo=dt.UTC).timestamp() * 1000)


@pytest.fixture
def con_and_health():
    c = duckdb.connect()
    health = ingest.load_all(c, ingest.source_for(SAMPLE))
    yield c, health
    c.close()
    registry.clear_cache()


def test_records_a_sample_per_measured_call():
    m = LatencyMeter()
    for _ in range(3):
        with m.measure("q"):
            pass
    assert m.stats("q")["n"] == 3


def test_p95_is_at_least_p50():
    m = LatencyMeter()
    for i in range(20):
        with m.measure("q"):
            # Deliberately uneven work so the two are not trivially equal.
            sum(range(i * 500))
    s = m.stats("q")
    assert s["p95Ms"] >= s["p50Ms"]
    assert s["maxMs"] >= s["p95Ms"]


def test_never_measured_label_is_none_not_zero():
    """A zero would read as "instant" on the console. A label nobody
    measured has no observation, and must say so."""
    assert LatencyMeter().stats("never") is None


def test_a_raising_call_still_records_its_sample():
    """The one that matters: if an exception skipped the measurement, p95
    would silently exclude every slow FAILING query -- precisely the
    population you care about."""
    m = LatencyMeter()
    with pytest.raises(ValueError):
        with m.measure("q"):
            raise ValueError("boom")
    assert m.stats("q")["n"] == 1


def test_snapshot_omits_empty_labels():
    m = LatencyMeter()
    m.samples.setdefault("empty", [])
    with m.measure("real"):
        pass
    snap = m.snapshot()
    assert "real" in snap and "empty" not in snap


def test_reset_clears_every_label():
    m = LatencyMeter()
    with m.measure("q"):
        pass
    m.reset()
    assert m.snapshot() == {}


def test_metric_query_is_instrumented(con_and_health):
    """registry.evaluate is one of the three instrumented call sites: the
    number that answers "DuckDB over Athena, on latency" comes from here."""
    con, _ = con_and_health
    LATENCY.reset()
    registry.clear_cache()
    registry.evaluate(con, registry.by_id("ota"), Slice.all(), WINDOW)
    assert LATENCY.stats("metric_query")["n"] == 1


def test_sweep_records_exactly_one_sample_per_sweep(con_and_health):
    con, health = con_and_health
    LATENCY.reset()
    sweep.sweep(con, sweep.Clock(CLOCK_MS), health)
    assert LATENCY.stats("sweep")["n"] == 1
    # And the sweep necessarily drove many metric queries underneath it.
    assert LATENCY.stats("metric_query")["n"] > 1
