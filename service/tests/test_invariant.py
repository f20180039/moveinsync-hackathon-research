"""Enforces spec 1.1 mechanically rather than by review: the raw-query
keyword (SELECT) is confined to registry.py and ingest.py, and there is no
`run_sql` tool anywhere in signaldesk/. Every other module reaches data
through registry.py's own functions -- this is why the module layout is not
negotiable.

A whole-word regex (`\\bSELECT\\b`), not a bare substring: several files
legitimately use the English word "selects"/"selection" in prose, which a
naive `"SELECT" in text` check would misfire on.
"""
from __future__ import annotations

import pathlib
import re

SIGNALDESK = pathlib.Path(__file__).resolve().parents[1] / "signaldesk"

_ALLOWED_SELECT_FILES = {"registry.py", "ingest.py"}
# Named explicitly in the fix-wave ruling -- checked individually (present
# only if the file exists; tools.py is a later task) as a belt-and-braces
# check over the blanket scan below.
_MUST_HAVE_NO_SELECT = ("tools.py", "model.py", "compose.py", "decompose.py", "actions.py")

_SELECT_RE = re.compile(r"\bSELECT\b", re.IGNORECASE)


def _py_files():
    return sorted(p for p in SIGNALDESK.glob("*.py") if p.name != "__init__.py")


def test_select_appears_only_in_registry_and_ingest():
    offenders = {}
    for path in _py_files():
        if path.name in _ALLOWED_SELECT_FILES:
            continue
        hits = _SELECT_RE.findall(path.read_text())
        if hits:
            offenders[path.name] = len(hits)
    assert not offenders, (
        f"SELECT found outside registry.py/ingest.py in: {offenders} -- "
        f"spec 1.1: nothing else queries raw tables")


def test_select_is_absent_from_the_named_modules_specifically():
    for name in _MUST_HAVE_NO_SELECT:
        path = SIGNALDESK / name
        if not path.exists():
            continue    # e.g. tools.py, Task 9 -- not built yet
        assert not _SELECT_RE.search(path.read_text()), f"{name} must contain no SELECT"


def test_no_run_sql_symbol_exists_anywhere():
    # The deliberate difference between this and a text-to-SQL demo: there is
    # no tool, function, or variable anywhere named run_sql.
    for path in _py_files():
        assert "run_sql" not in path.read_text(), (
            f"{path.name} must not define or reference run_sql")
