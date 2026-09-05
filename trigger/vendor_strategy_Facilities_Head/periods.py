"""Which window is being analysed, resolved from the data rather than the
wall clock -- the dataset is static, so "today" is the last day it contains.

The sample carries three whole months (2026-05, 2026-06, 2026-07). That does
not line up with a calendar quarter: Q2 2026 would hold only May and June,
Q3 only July. So the DEFAULT quarter is the last three consecutive months
present -- a rolling quarter -- which is the window that actually supports
month-over-month trend analysis. `--quarter 2026Q2` forces the calendar one,
and every report states which it used. No data is invented to fill a
calendar quarter out.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

DAY_MS = 86_400_000


@dataclass(frozen=True)
class Window:
    label: str
    kind: str            # day | month | quarter
    start_ms: int
    end_ms: int          # exclusive
    note: str = ""
    sub_labels: tuple[str, ...] = ()      # months inside a quarter, days inside a month


def _epoch_ms(d: date, off_min: int) -> int:
    """Local midnight of `d`, as an absolute epoch-ms instant."""
    utc_midnight = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return int(utc_midnight.timestamp() * 1000) - off_min * 60_000


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def months_present(con) -> list[str]:
    rows = con.sql("""
        SELECT strftime(to_timestamp(scheduled_at / 1000), '%Y-%m') AS m
        FROM trips GROUP BY 1 ORDER BY 1
    """).fetchall()
    return [r[0] for r in rows]


def days_present(con, off_min: int) -> list[str]:
    rows = con.sql(f"""
        SELECT strftime(to_timestamp((scheduled_at + {off_min * 60_000}) / 1000),
                        '%Y-%m-%d') AS d
        FROM trips GROUP BY 1 ORDER BY 1
    """).fetchall()
    return [r[0] for r in rows]


def day_window(con, cfg) -> Window:
    """One operating day. Default: the last day the data contains."""
    days = days_present(con, cfg.tz_offset_min)
    if not days:
        raise ValueError("no trips in the dataset")
    chosen = cfg.date or days[-1]
    if chosen not in days:
        raise ValueError(f"no trips on {chosen}; data covers {days[0]}..{days[-1]}")
    d = datetime.strptime(chosen, "%Y-%m-%d").date()
    start = _epoch_ms(d, cfg.tz_offset_min)
    note = "" if cfg.date else "last operating day in the dataset"
    return Window(chosen, "day", start, start + DAY_MS, note)


def month_window(con, cfg) -> Window:
    """One calendar month. Default: the last month present in the data."""
    months = months_present(con)
    if not months:
        raise ValueError("no trips in the dataset")
    chosen = cfg.month or months[-1]
    if chosen not in months:
        raise ValueError(f"no trips in {chosen}; data covers {', '.join(months)}")
    y, m = (int(p) for p in chosen.split("-"))
    ny, nm = _next_month(y, m)
    start = _epoch_ms(date(y, m, 1), cfg.tz_offset_min)
    end = _epoch_ms(date(ny, nm, 1), cfg.tz_offset_min)
    note = "" if cfg.month else "last month in the dataset"
    days = [d for d in days_present(con, cfg.tz_offset_min) if d.startswith(chosen)]
    return Window(chosen, "month", start, end, note, tuple(days))


def quarter_window(con, cfg) -> Window:
    """Three months. Default: the last three consecutive months present."""
    months = months_present(con)
    if not months:
        raise ValueError("no trips in the dataset")

    if cfg.quarter:
        q = cfg.quarter.upper().replace("-", "")
        year, qn = int(q[:4]), int(q[-1])
        first = 3 * (qn - 1) + 1
        chosen = [f"{year}-{first + i:02d}" for i in range(3)]
        present = [m for m in chosen if m in months]
        if not present:
            raise ValueError(f"no trips in {cfg.quarter}; data covers {', '.join(months)}")
        missing = [m for m in chosen if m not in months]
        note = f"calendar quarter {cfg.quarter}"
        if missing:
            note += (f" — {', '.join(missing)} carries no trips, so the quarter is "
                     f"analysed on {len(present)} of 3 months")
        label = cfg.quarter
    else:
        present = months[-3:]
        label = f"{present[0]}..{present[-1]}"
        note = ("rolling quarter: the last three months present. The dataset does "
                "not align to a calendar quarter, and no data was invented to make "
                "it. Use --quarter to force a calendar one.")

    y0, m0 = (int(p) for p in present[0].split("-"))
    y1, m1 = (int(p) for p in present[-1].split("-"))
    ny, nm = _next_month(y1, m1)
    start = _epoch_ms(date(y0, m0, 1), cfg.tz_offset_min)
    end = _epoch_ms(date(ny, nm, 1), cfg.tz_offset_min)
    return Window(label, "quarter", start, end, note, tuple(present))


def month_windows(con, cfg, labels) -> list[Window]:
    """The sub-windows a quarter's trend analysis walks."""
    out = []
    for m in labels:
        y, mm = (int(p) for p in m.split("-"))
        ny, nm = _next_month(y, mm)
        out.append(Window(m, "month",
                          _epoch_ms(date(y, mm, 1), cfg.tz_offset_min),
                          _epoch_ms(date(ny, nm, 1), cfg.tz_offset_min)))
    return out


def thirds(window: Window) -> list[Window]:
    """A month split into three, for within-month trend (start / middle / end)."""
    span = (window.end_ms - window.start_ms) // 3
    names = ("first third", "middle third", "final third")
    return [Window(names[i], "part", window.start_ms + i * span,
                   window.start_ms + (i + 1) * span if i < 2 else window.end_ms)
            for i in range(3)]
