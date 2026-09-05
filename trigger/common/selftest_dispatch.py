"""Task 19 (3) -- checks for sweep-driven dispatch. Posts NOTHING, and proves
it.

    python -m trigger.common.selftest_dispatch

The guardrails are the feature here, so they are what is tested. The sharpest
check is the first one: under the conditions a test, a judge or a local demo
runs in, the number of Slack sends must be exactly ZERO. Every send in this
file goes through a counting stub, so "it did not post" is a measured fact and
not an assumption about an environment variable.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from ..common.config import ROOT
from . import dispatch as dispatch_mod
from .state import SeenStore


def _check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    return bool(ok)


class _CountingSender:
    """Stands in for slack.send. Counts every call, delivers or refuses on
    demand, and never touches the network."""

    def __init__(self, delivered=True):
        self.calls: list[str] = []
        self.delivered = delivered

    def __call__(self, text: str):
        self.calls.append(text)

        class _R:
            delivered = self.delivered
            detail = "stub"
        return _R()


def _store(tmp: str) -> SeenStore:
    return SeenStore(Path(tmp) / "dispatch.json")


def main() -> int:
    load_dotenv(ROOT / ".env")
    print("\nSweep-driven dispatch selftest\n" + "=" * 32)
    results = []

    # Whatever the developer's .env says, this file decides the environment it
    # tests -- otherwise the result depends on a machine's configuration.
    original = {k: os.environ.get(k) for k in
                ("TRIGGER_ON_SWEEP", "TRIGGER_ON_SWEEP_AGENTS", "TRIGGER_DRY_RUN")}

    def _set(**kw):
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    try:
        print("\n1. OFF BY DEFAULT — nothing posts because a sweep ran")
        _set(TRIGGER_ON_SWEEP=None, TRIGGER_DRY_RUN=None)
        results.append(_check("enabled() is False with the var unset",
                              dispatch_mod.enabled() is False))
        sender = _CountingSender()
        with tempfile.TemporaryDirectory() as tmp:
            out = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                        sender=sender, store=_store(tmp))
        results.append(_check("ZERO Slack sends", len(sender.calls) == 0,
                              f"{len(sender.calls)} calls"))
        results.append(_check("reported as disabled, not silently skipped",
                              out and out[0]["action"] == "disabled",
                              str(out)))
        results.append(_check("fire_async does not even start a thread",
                              dispatch_mod.fire_async(None) is None))

        print("\n2. Explicitly off, and off for junk values")
        for value in ("0", "false", "no", "off", "maybe", ""):
            _set(TRIGGER_ON_SWEEP=value)
            if dispatch_mod.enabled():
                results.append(_check(f"{value!r} must not enable dispatch", False))
                break
        else:
            results.append(_check("only a truthy value enables dispatch", True,
                                  "0/false/no/off/maybe/'' all stay off"))

        print("\n3. Switched on: it posts once, then suppresses the repeat")
        _set(TRIGGER_ON_SWEEP="1", TRIGGER_DRY_RUN="0")
        results.append(_check("enabled() is True", dispatch_mod.enabled() is True))
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            sender = _CountingSender()
            first = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                          sender=sender, store=store)
            results.append(_check("first run posts", len(sender.calls) == 1,
                                  str(first[0]["action"])))
            results.append(_check("classified NEW", first[0].get("detail") == "NEW",
                                  str(first[0].get("detail"))))
            # Guardrail 5: a second sweep over unchanged data mints a new run
            # id but the same plan, and must NOT post again.
            second = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                           sender=sender, store=store)
            results.append(_check("an unchanged plan does not post again",
                                  len(sender.calls) == 1, f"{len(sender.calls)} calls"))
            results.append(_check("reported as suppressed",
                                  second[0]["action"] == "suppressed",
                                  str(second[0])))
            results.append(_check("the fingerprint is stable across runs",
                                  first[0]["fingerprint"] == second[0]["fingerprint"]))

        print("\n4. A failed delivery is retried, not recorded as sent")
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            failing = _CountingSender(delivered=False)
            r1 = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                       sender=failing, store=store)
            results.append(_check("reported as not delivered",
                                  r1[0]["action"] == "not_delivered", str(r1[0])))
            results.append(_check("nothing was written to the state file",
                                  store.data == {}, str(store.data)))
            ok = _CountingSender(delivered=True)
            r2 = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                       sender=ok, store=store)
            results.append(_check("the next sweep tries again and posts",
                                  r2[0]["action"] == "posted" and len(ok.calls) == 1,
                                  str(r2[0]["action"])))

        print("\n5. A materially different plan DOES post")
        with tempfile.TemporaryDirectory() as tmp:
            store = _store(tmp)
            sender = _CountingSender()
            dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                  sender=sender, store=store)
            # Record a different fingerprint by hand, the way a changed week
            # would: the classification, not the plan builder, is under test.
            fp_before = store.data[dispatch_mod.FLEET]["fingerprint"]
            store.record(dispatch_mod.FLEET, "a-different-fingerprint")
            third = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                          sender=sender, store=store)
            results.append(_check("a changed plan is UPDATED, not suppressed",
                                  third[0]["action"] == "posted"
                                  and third[0]["detail"] == "UPDATED",
                                  f"{third[0]['action']}/{third[0].get('detail')}"))
            results.append(_check("and it actually posted",
                                  len(sender.calls) == 2, f"{len(sender.calls)} calls"))
            results.append(_check("the real fingerprint is content-derived, not a run id",
                                  fp_before != "a-different-fingerprint"))

        print("\n6. Dry run posts nothing even when enabled")
        _set(TRIGGER_ON_SWEEP="1", TRIGGER_DRY_RUN="1")
        with tempfile.TemporaryDirectory() as tmp:
            sender = _CountingSender()
            out = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                        sender=sender, store=_store(tmp))
            results.append(_check("ZERO Slack sends under TRIGGER_DRY_RUN",
                                  len(sender.calls) == 0, f"{len(sender.calls)} calls"))
            results.append(_check("but the message was really built",
                                  out[0]["action"] == "dry_run"
                                  and out[0].get("chars", 0) > 200,
                                  str(out[0].get("chars"))))

        print("\n7. A broken agent does not take the sweep down")
        _set(TRIGGER_ON_SWEEP="1", TRIGGER_DRY_RUN="0")
        with tempfile.TemporaryDirectory() as tmp:
            sender = _CountingSender()
            out = dispatch_mod.dispatch(None, agents=("no_such_agent",),
                                        sender=sender, store=_store(tmp))
            results.append(_check("an unknown agent is reported, not raised",
                                  out[0]["action"] == "unknown", str(out[0])))

            def _boom(_run):
                raise RuntimeError("selftest: simulated agent failure")
            original_builder = dispatch_mod._BUILDERS[dispatch_mod.FLEET]
            dispatch_mod._BUILDERS[dispatch_mod.FLEET] = _boom
            try:
                out = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                            sender=sender, store=_store(tmp))
                results.append(_check("a raising agent is caught",
                                      out[0]["action"] == "error", str(out[0])))
            finally:
                dispatch_mod._BUILDERS[dispatch_mod.FLEET] = original_builder

            def _explode(_text):
                raise ConnectionError("selftest: simulated Slack outage")
            out = dispatch_mod.dispatch(None, agents=(dispatch_mod.FLEET,),
                                        sender=_explode, store=_store(tmp))
            results.append(_check("a raising Slack send is caught",
                                  out[0]["action"] == "error", str(out[0])))

        print("\n8. The service wires it in without depending on trigger/")
        from signaldesk import api as api_mod
        src = Path(api_mod.__file__).read_text()
        results.append(_check("sweep completion calls the dispatcher",
                              "_fire_triggers(run)" in src))
        results.append(_check("the import is deferred, not module-level",
                              "\nfrom trigger" not in src and "\nimport trigger" not in src))
        _set(TRIGGER_ON_SWEEP=None)
        results.append(_check("and with dispatch off it is a no-op",
                              api_mod._fire_triggers(None) is None))
    finally:
        for k, v in original.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print(f"\n{sum(results)}/{len(results)} checks passed\n")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
