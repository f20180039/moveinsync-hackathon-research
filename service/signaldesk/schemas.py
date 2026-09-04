from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import total_ordering
from typing import Optional

from . import constants


@total_ordering
class Tier(Enum):
    """Ordered, compared ordinally, NEVER summed into a score. Summing would let
    three mild issues outrank one genuine breach.

    total_ordering is deliberate rather than decorative. Defining only __lt__
    happens to work -- `BREACH > CONCERN` and `max(...)` resolve through
    Python's reflected-comparison fallback -- but the whole ranking rule and
    the delivery routing depend on `>` and `max()`, and that fallback silently
    stops applying the moment anyone gives Tier a custom __eq__. Generating the
    operators makes the guarantee explicit instead of incidental.
    """
    PASS = 0
    WATCH = 1
    CONCERN = 2
    BREACH = 3

    def __lt__(self, other: "Tier") -> bool:
        if not isinstance(other, Tier):
            return NotImplemented
        return self.value < other.value


class Direction(Enum):
    HIGHER = "HIGHER"
    LOWER = "LOWER"


class ReferenceKind(Enum):
    TREND = "TREND"
    TARGET = "TARGET"
    PEER = "PEER"


class Cause(Enum):
    ON_REFERENCE = "ON_REFERENCE"      # a PASS carries no accusatory cause
    BELOW_TARGET = "BELOW_TARGET"
    TREND_REGRESSION = "TREND_REGRESSION"
    PEER_LAGGARD = "PEER_LAGGARD"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    DATA_GAP = "DATA_GAP"


class Audience(Enum):
    TRANSPORT_MANAGER = "TRANSPORT_MANAGER"
    FACILITIES_HEAD = "FACILITIES_HEAD"
    LINE_MANAGER = "LINE_MANAGER"


class Dimension(Enum):
    """The enumerated slice dimensions. The model selects from these; it never
    composes a join. These column names are the only ones that reach SQL —
    values are always bound as parameters."""
    VENDOR = "t.vendor_id"
    SITE = "t.site_id"
    SHIFT = "t.shift"
    MODE = "t.mode"
    DIRECTION = "t.direction"
    NONE = ""

    @property
    def column(self) -> str:
        if self is Dimension.NONE:
            raise ValueError("Dimension.NONE has no column")
        return self.value

    @classmethod
    def parse(cls, raw: str) -> "Dimension":
        for d in cls:
            if d.name.lower() == (raw or "").lower():
                return d
        valid = ", ".join(d.name for d in cls)
        raise ValueError(f"unknown dimension {raw!r}; valid values are {valid}")


@dataclass(frozen=True)
class Slice:
    dim: Dimension
    value: Optional[str] = None

    def __post_init__(self):
        if self.dim is Dimension.NONE and self.value is not None:
            raise ValueError("Dimension.NONE must carry a null value")
        if self.dim is not Dimension.NONE and not self.value:
            raise ValueError(f"dimension {self.dim.name} requires a value")

    @staticmethod
    def all() -> "Slice":
        return Slice(Dimension.NONE, None)

    @property
    def label(self) -> str:
        return "overall" if self.dim is Dimension.NONE else f"{self.dim.name.lower()} {self.value}"


WEEK_MS = 7 * 86_400_000


@dataclass(frozen=True)
class Window:
    """Half-open: [start_ms, end_ms)."""
    start_ms: int
    end_ms: int

    def __post_init__(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("window end must be after start")

    @staticmethod
    def week_ending(end_ms: int) -> "Window":
        return Window(end_ms - WEEK_MS, end_ms)

    def shifted_back(self, n: int) -> "Window":
        length = self.end_ms - self.start_ms
        new_end = self.end_ms - n * length
        return Window(new_end - length, new_end)

    @property
    def label(self) -> str:
        import datetime as _dt
        fmt = lambda ms: _dt.datetime.fromtimestamp(ms / 1000, _dt.UTC).strftime("%Y-%m-%d")
        return f"{fmt(self.start_ms)}..{fmt(self.end_ms - 1)}"


@dataclass(frozen=True)
class Reference:
    kind: ReferenceKind
    value: float
    label: str


@dataclass(frozen=True)
class Metric:
    """The SQL here is the ONLY SQL outside ingest.py: nothing else queries raw
    tables. It must aggregate to exactly one number, bind the window as two
    parameters in order, and contain the token {{SLICE}}."""
    id: str
    label: str
    unit: str
    better: Direction
    sql: str
    refs: tuple[ReferenceKind, ...]
    source: str                       # the feed/table the confidence comes from
    required_columns: tuple[str, ...]
    target: Optional[float] = None
    hard_target: bool = False         # deviation 2: breaches on ANY shortfall

    def __post_init__(self):
        declares = ReferenceKind.TARGET in self.refs
        if declares and self.target is None:
            raise ValueError(f"metric {self.id} declares TARGET but has no target value")
        if not declares and self.target is not None:
            raise ValueError(f"metric {self.id} has a target but does not declare TARGET")
        if self.hard_target and self.target is None:
            raise ValueError(f"metric {self.id} has a hard target but no target value")
        if "{{SLICE}}" not in self.sql:
            raise ValueError(f"metric {self.id} SQL has no {{{{SLICE}}}} token")


@dataclass(frozen=True)
class FeedHealth:
    feed: str
    rows_loaded: int
    rows_rejected: int
    unmatched_keys: int
    null_critical_fields: int
    confidence: float

    @staticmethod
    def of(feed, rows_loaded, rows_rejected, unmatched_keys, null_critical_fields) -> "FeedHealth":
        considered = rows_loaded + rows_rejected
        raw = 1.0 if considered == 0 else 1.0 - (
            rows_rejected + unmatched_keys + null_critical_fields) / considered
        return FeedHealth(feed, rows_loaded, rows_rejected, unmatched_keys,
                          null_critical_fields, max(0.0, min(1.0, raw)))

    @property
    def must_be_disclosed(self) -> bool:
        return self.confidence < constants.DISCLOSE_CONFIDENCE_BELOW


@dataclass(frozen=True)
class Finding:
    """The unit of everything downstream: the console renders it, the narrative
    is written from it, delivery routes on it.

    Deviation 1: gap is delta x reference, so POSITIVE ALWAYS MEANS WORSE, for
    both metric directions, and the sign agrees with the tier by construction.
    Spec §6.2's "observed - reference" wording is superseded by §6.3.

    evidence_sql is not decoration. It is the answer to "where did this number
    come from", as a query the reader can run rather than a claim.
    """
    id: str
    metric_id: str
    slice: Slice
    window: Window
    observed: float
    refs: tuple[Reference, ...]
    tier: Tier
    cause: Cause
    gap: float
    confidence: float
    audiences: frozenset[Audience]
    evidence_sql: str

    def __post_init__(self):
        if self.tier is Tier.PASS and self.gap > 0:
            raise ValueError(
                f"finding {self.id} is a PASS carrying a positive (worse-than-reference) gap")

    @property
    def must_disclose_confidence(self) -> bool:
        return self.confidence < constants.DISCLOSE_CONFIDENCE_BELOW


def finding_id(metric_id: str, slc: Slice, window: Window) -> str:
    """Stable across runs, so a finding can be re-opened by URL and re-explained."""
    import hashlib
    material = "|".join([metric_id, slc.dim.name, slc.value or "",
                         str(window.start_ms), str(window.end_ms)])
    return hashlib.sha256(material.encode()).hexdigest()[:12]
