"""Task 19 -- which RUN and which WINDOW a trigger agent is speaking for.

THE PROBLEM THIS EXISTS TO FIX. Every agent under `trigger/` used to open its
own DuckDB and derive its own window from the data ("the day after the last
trip", "the last 28 days"). Nothing tied that to the sweep the console shows.
So a Slack brief and the console could each be internally correct and still
quote different numbers for the same morning -- the worst kind of wrong on a
stage, because both sides look right in isolation and neither can be checked
against the other.

The fix is provenance, not just plumbing: an agent takes the SAME window the
sweep used, and stamps the run id on its output, so every Slack message says
which run it came from and a reader can open that run in the console and match
the figures line for line.

WHY HTTP AND NOT THE IN-PROCESS STORE. The agents run as separate processes
(cron, a sleep loop, a one-off `python -m trigger....`). `api.STORE` lives in
the service's own process, so importing it would give an empty store, not the
run the console is showing. The service already exposes what is needed --
`/api/health` (clock, status) and `/api/runs/latest/findings` (run id, exact
window bounds) -- so this reads those.

WHEN THE SERVICE IS UNREACHABLE the agent still runs, on its own
self-derived window, exactly as it did before -- and SAYS SO in the output.
A brief that quietly diverges from the console is the failure being fixed
here; a brief that names its own provenance is not. `RunContext.source` is
"service" or "local", and `provenance_line()` is a sentence written for the
Slack message, not a debug log.

Only the WINDOW and the RUN ID come from the service. Each agent keeps its own
DuckDB for detail queries -- they ask questions (boarding status, cab
registrations, delay reasons) that no endpoint exposes, and re-routing those
through HTTP would be a rewrite for no gain.

No new dependencies: urllib from the standard library, one short timeout, and
every failure path returns a local context instead of raising.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import env_int

logger = logging.getLogger("trigger")

DAY_MS = 86_400_000

# Where the service is. Default matches the repo's own local run
# (uvicorn signaldesk.api:app --port 8797, see the README's run command).
DEFAULT_SERVICE_URL = "http://127.0.0.1:8797"


def service_url() -> str:
    return (os.environ.get("TRIGGER_SERVICE_URL", "").strip()
            or DEFAULT_SERVICE_URL).rstrip("/")


def timeout_s() -> float:
    """Short on purpose: an unreachable service must cost a couple of seconds
    and then fall back, never hang a cron job."""
    return env_int("TRIGGER_SERVICE_TIMEOUT_S", 5)


@dataclass(frozen=True)
class RunContext:
    """The run an agent is speaking for.

    `source` is "service" (reconciled -- these are the sweep's own run id and
    window) or "local" (self-derived; the output must say so). A local context
    carries no run id, deliberately: inventing one would be worse than having
    none, because a reader could not tell a reconciled brief from a guess.
    """
    source: str                      # "service" | "local"
    run_id: str | None
    window_start_ms: int | None
    window_end_ms: int | None
    window_label: str | None
    window_kind: str | None
    clock_ms: int | None
    url: str
    detail: str                      # why local, when local

    @property
    def reconciled(self) -> bool:
        return self.source == "service" and self.run_id is not None

    @property
    def window_days(self) -> int | None:
        if self.window_start_ms is None or self.window_end_ms is None:
            return None
        return (self.window_end_ms - self.window_start_ms) // DAY_MS

    def provenance_line(self) -> str:
        """The sentence that goes in the Slack message. This is the whole
        point of the module: a reader must be able to tell, without asking,
        whether this brief matches the console."""
        if self.reconciled:
            return (f"Run `{self.run_id}` · window {self.window_label} "
                    f"({self.window_kind}) · reconciled with the console at {self.url}")
        return (f"⚠️ Not reconciled with a sweep run: {self.detail}. "
                f"Window derived locally from the data, so these figures may "
                f"not match the console.")

    def as_json(self) -> dict:
        return {
            "source": self.source,
            "runId": self.run_id,
            "windowStartMs": self.window_start_ms,
            "windowEndMs": self.window_end_ms,
            "windowLabel": self.window_label,
            "windowKind": self.window_kind,
            "clockMs": self.clock_ms,
            "serviceUrl": self.url,
            "detail": self.detail,
        }


def _local(url: str, detail: str) -> RunContext:
    return RunContext("local", None, None, None, None, None, None, url, detail)


def _get(url: str, timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, json.JSONDecodeError, ValueError) as exc:
        logger.info("trigger: %s unreachable (%s)", url, type(exc).__name__)
        return None


def resolve(window_kind: str = "week", url: str | None = None) -> RunContext:
    """The run context for this agent's output.

    Never raises and never blocks for long: any failure -- service down, no
    sweep run yet, a response missing the window bounds -- returns a LOCAL
    context whose `detail` says which of those it was, so the agent can carry
    on and the message can be honest about it.

    `windowStartMs`/`windowEndMs` are required for a reconciled context. A
    response carrying only `windowLabel` is treated as NOT reconciled: a
    label is a thing to print, not a window a query can bind, and quietly
    re-deriving the bounds from the label is exactly the silent divergence
    this module exists to stop.
    """
    base = (url or service_url()).rstrip("/")
    t = timeout_s()

    health = _get(f"{base}/api/health", t)
    if health is None:
        return _local(base, f"the service at {base} did not answer")
    if health.get("status") != "ok":
        return _local(base, f"the service at {base} reports status "
                            f"{health.get('status')!r} (no run yet)")

    run = _get(f"{base}/api/runs/latest/findings?window={window_kind}", t)
    if run is None:
        return _local(base, f"no {window_kind} run available from {base}")

    start, end = run.get("windowStartMs"), run.get("windowEndMs")
    run_id = run.get("runId")
    if start is None or end is None or not run_id:
        return _local(base, f"the {window_kind} run from {base} carried no "
                            f"window bounds to reconcile against")

    return RunContext("service", str(run_id), int(start), int(end),
                      run.get("windowLabel"), run.get("windowKind"),
                      health.get("clock"), base, "")
