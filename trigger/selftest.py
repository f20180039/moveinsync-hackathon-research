"""Back-compat shim -- see `run_daily.py`. Prefer
`python -m trigger.shift_planning_TransportManager.selftest`."""
from __future__ import annotations

import sys

from .shift_planning_TransportManager.selftest import main

if __name__ == "__main__":
    sys.exit(main())
