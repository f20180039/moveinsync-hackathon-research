import os

from dotenv import load_dotenv

load_dotenv()

# The month sweep that startup() kicks off is a DAEMON THREAD: it keeps
# calling registry.evaluate for ~90s after the app is constructed. Under
# `pytest -q` that thread outlives the test that started it and goes on
# recording `metric_query` samples into the process-wide LATENCY while a
# LATER test asserts an exact count -- test_telemetry's
# test_metric_query_is_instrumented failed with `3 == 1` on one run and
# `2 == 1` on the next, and a count that changes run to run is a race, not
# a logic error. It passes alone and alongside test_api (75 passed).
#
# api.py already has the switch for exactly this ("Off with
# SIGNALDESK_STARTUP_MONTH_SWEEP=0 for a cold start"). Setting it here, for
# the whole session, means no test starts the thread -- no test asserts on
# month-sweep behaviour, so nothing loses coverage. A test that ever wants
# the thread should set the variable back to "1" itself rather than removing
# this default and reintroducing the race for everything else.
os.environ.setdefault("SIGNALDESK_STARTUP_MONTH_SWEEP", "0")
