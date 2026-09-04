#!/usr/bin/env python3
"""Verify the three Sarvam capabilities this build depends on, before build day.

    1. auth + completion   -> Task 6 (the model-composed brief)
    2. TOOL CALLING        -> Task 10 (the interrogation panel) needs this
    3. Indic translation   -> Task 11 (vernacular feedback)

Prints no secrets. Safe to paste the output into a channel.

Usage, from the repo root:
    set -a && . ./.env && set +a && python3 scripts/check_sarvam.py

Replaces scripts/check-sarvam.sh, which had two defects: it crashed when the
API returned message.content = null (a present key with a null value, so
.get("content", "") returns None, not ""), and its verdict block printed a
static legend that read like a computed result. Both are fixed here; the
verdict below is derived from what actually happened.

The first run of that script produced finish_reason "length" with empty
content on max_tokens of 16/64/256. That is truncation, not an unsupported
parameter -- sarvam-105b appears to emit reasoning tokens before content, so
the budgets here are deliberately generous.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://api.sarvam.ai/v1/chat/completions"
MODEL = "sarvam-105b"  # Sarvam-M is deprecated and no longer served
TIMEOUT = 120

KEY = os.environ.get("SARVAM_API_KEY", "")
if not KEY:
    print("SARVAM_API_KEY is not set in this shell.")
    print("Run:  set -a && . ./.env && set +a && python3 scripts/check_sarvam.py")
    sys.exit(2)
print(f"key: set ({len(KEY)} chars)   model: {MODEL}\n")


def call(payload: dict) -> tuple[dict | None, str | None]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE, data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return json.loads(raw), f"HTTP {e.code}"
        except Exception:
            return None, f"HTTP {e.code}: {raw[:400]}"
    except Exception as e:  # timeout, DNS, TLS
        return None, f"{type(e).__name__}: {e}"


def choice(d: dict) -> dict:
    ch = d.get("choices") or [{}]
    return ch[0] if ch else {}


def content_of(msg: dict) -> str:
    """message.content can be absent, null, or a list of parts. Handle all three."""
    c = msg.get("content")
    if c is None:
        return ""
    if isinstance(c, list):  # some OpenAI-compatible servers return parts
        return "".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c)


def show_usage(d: dict) -> dict:
    u = d.get("usage") or {}
    keep = {k: u.get(k) for k in
            ("prompt_tokens", "completion_tokens", "total_tokens") if u.get(k) is not None}
    extra = {k: v for k, v in u.items() if "reason" in k.lower()}
    print(f"      usage: {keep or 'ABSENT'}" + (f"  reasoning: {extra}" if extra else ""))
    return u


def unexpected(d: dict, msg: dict) -> None:
    """When content is empty, say WHERE the tokens went instead of guessing."""
    print(f"      message keys: {sorted(msg.keys())}")
    for k in ("reasoning", "reasoning_content", "thinking"):
        if msg.get(k):
            print(f"      !! '{k}' is populated -- the budget went to reasoning tokens.")
            print("         Raise max_tokens further, or set it per call in model.py.")
    print(f"      top-level keys: {sorted(d.keys())}")


results: dict[str, bool] = {}

# ------------------------------------------------------------- 1. completion
print("=== 1/3  auth + completion " + "=" * 44)
d, err = call({
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "Reply with exactly the word READY and nothing else."},
        {"role": "user", "content": "Are you there?"},
    ],
    "max_tokens": 1024,
})
if err and d is None:
    print(f"FAIL  {err}")
    results["completion"] = False
elif d is not None and "error" in d:
    print(f"FAIL  {json.dumps(d['error'])[:400]}")
    results["completion"] = False
else:
    c = choice(d)
    msg = c.get("message") or {}
    text = content_of(msg)
    fr = c.get("finish_reason")
    print(f"      finish_reason: {fr}")
    print(f"      content: {text[:80]!r}")
    show_usage(d)
    if text.strip():
        print("PASS  the model answers and the key authenticates.")
        results["completion"] = True
    else:
        print("FAIL  empty content.")
        if fr == "length":
            print("      finish_reason 'length' with 1024 tokens means the whole budget")
            print("      went somewhere other than content.")
        unexpected(d, msg)
        results["completion"] = False
print()

# ------------------------------------------------------------ 2. tool calling
print("=== 2/3  TOOL CALLING (the one that matters) " + "=" * 27)
TOOL = {
    "type": "function",
    "function": {
        "name": "get_metric",
        "description": "Read one metric for one slice over the current window, with its reference points.",
        "parameters": {
            "type": "object",
            "properties": {
                "metricId": {"type": "string", "enum": ["ota", "otd", "vendor_ota", "sla_breach"]},
                "dimension": {"type": "string",
                              "enum": ["VENDOR", "SITE", "SHIFT", "MODE", "DIRECTION", "NONE"]},
                "value": {"type": "string", "description": "the dimension value; omit when NONE"},
            },
            "required": ["metricId", "dimension"],
        },
    },
}
MSGS = [
    {"role": "system", "content": "You have no data of your own. Use the tool to answer. "
                                  "Never state a figure you did not receive from a tool."},
    {"role": "user", "content": "What is the on-time arrival for vendor V07 this week?"},
]


def try_tools(label: str, tool_choice) -> bool:
    print(f"  -- {label}")
    d, err = call({"model": MODEL, "messages": MSGS, "tools": [TOOL],
                   "tool_choice": tool_choice, "max_tokens": 2048})
    if err and d is None:
        print(f"     FAIL  {err}")
        return False
    if d is not None and "error" in d:
        e = json.dumps(d["error"])
        print(f"     FAIL  {e[:400]}")
        if any(w in e.lower() for w in ("tool", "function", "unsupported", "unrecognized")):
            print("     ^^ the API REJECTED the tools parameter itself. That is the")
            print("        signal that tool calling is genuinely unavailable.")
        return False
    c = choice(d)
    msg = c.get("message") or {}
    tcs = msg.get("tool_calls") or []
    print(f"     finish_reason: {c.get('finish_reason')}")
    show_usage(d)
    if tcs:
        fn = (tcs[0].get("function") or {})
        print(f"     PASS  tool: {fn.get('name')}  args: {fn.get('arguments')}")
        try:
            a = json.loads(fn.get("arguments") or "{}")
            ok = (a.get("metricId") in ("ota", "otd", "vendor_ota", "sla_breach")
                  and a.get("dimension") in ("VENDOR", "SITE", "SHIFT", "MODE",
                                             "DIRECTION", "NONE"))
            print(f"     args respect the enums: {ok} -> {a}")
            if not ok:
                print("     NOTE: it invented an argument value. tools.py validates before")
                print("           executing and refuses by name, so this is handled -- but")
                print("           keep MAX_TOOL_CALLS at 4 so a retry loop stays bounded.")
        except Exception as e:
            print(f"     args are not valid JSON ({e}) -- parse defensively in tools.py")
        return True
    text = content_of(msg)
    print(f"     no tool_calls. content: {text[:160]!r}")
    unexpected(d, msg)
    return False


ok = try_tools('tool_choice="auto"', "auto")
if not ok:
    print()
    ok = try_tools('tool_choice forced to get_metric',
                   {"type": "function", "function": {"name": "get_metric"}})
results["tools"] = ok
print()

# ------------------------------------------------------------- 3. translation
print("=== 3/3  translation (Indic -> English) " + "=" * 31)
d, err = call({
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "Translate the employee transport feedback into English. "
                                      "Reply with the translation only, no commentary."},
        {"role": "user", "content": "Cab bahut late tha, koi soochna nahi mili"},
    ],
    "max_tokens": 1024,
})
if err and d is None:
    print(f"FAIL  {err}")
    results["translation"] = False
elif d is not None and "error" in d:
    print(f"FAIL  {json.dumps(d['error'])[:400]}")
    results["translation"] = False
else:
    c = choice(d)
    msg = c.get("message") or {}
    text = content_of(msg).strip()
    print(f"      finish_reason: {c.get('finish_reason')}")
    print(f"      translation: {text[:160]!r}")
    show_usage(d)
    if text:
        markers = [w for w in ("late", "delay", "waited", "no update", "not inform",
                               "no inform", "information")
                   if w in text.lower()]
        print(f"      sentiment-lexicon markers found: {markers or 'NONE'}")
        if not markers:
            print("      NOTE: the lexicon scores the TRANSLATED text. If Sarvam's wording")
            print("            never matches a marker, experience scores neutral and the")
            print("            metric says nothing. Widen SENTIMENT_LEXICON to match what")
            print("            Sarvam actually returns -- do not hand-tune the translation.")
        results["translation"] = True
    else:
        print("FAIL  empty content.")
        unexpected(d, msg)
        results["translation"] = False
print()

# ------------------------------------------------------------------- verdict
print("=== verdict (computed, not a legend) " + "=" * 34)
label = {"completion": "1 completion  -> Task 6, the model-composed brief",
         "tools": "2 tool calling -> Task 10, the interrogation panel",
         "translation": "3 translation  -> Task 11, vernacular feedback"}
for k in ("completion", "tools", "translation"):
    print(f"  {'PASS' if results.get(k) else 'FAIL'}  {label[k]}")
print()
if not results.get("completion"):
    print("  Completion failing is the serious one: no model output at all. The")
    print("  template brief still clears the mandatory bar, so Tier 1 survives --")
    print("  but check the key and the credit balance before assuming anything else.")
if not results.get("tools"):
    print("  Tool calling failing means CUT Task 10 and beat 8 of the demo script.")
    print("  Decide tonight so the deck never promises it. Everything else stands:")
    print("  the four tools are only the *interrogation* path, not the sweep.")
if not results.get("translation"):
    print("  Translation failing means Task 11 degrades as designed: untranslated")
    print("  comments score neutral, experience reports low confidence, and the rule")
    print("  caps at WATCH. That path is already tested -- it is not a blocker.")
if all(results.get(k) for k in ("completion", "tools", "translation")):
    print("  All three viable. Note the credit balance in the Sarvam dashboard.")
sys.exit(0 if results.get("completion") else 1)
