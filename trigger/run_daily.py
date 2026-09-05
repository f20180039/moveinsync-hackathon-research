"""Back-compat shim. The Transport Manager agent moved to
`trigger/shift_planning_TransportManager/` when a second agent arrived; this keeps
`python -m trigger.run_daily` working exactly as before.

Prefer `python -m trigger.shift_planning_TransportManager.run_daily`.
"""
from __future__ import annotations

import sys

from .shift_planning_TransportManager.run_daily import run

if __name__ == "__main__":
    sys.exit(run())
