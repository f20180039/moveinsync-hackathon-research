#!/bin/sh
# Verify the three Sarvam capabilities this build depends on, BEFORE build day.
#
#   1. auth + completion  -> Task 6 (the brief) is impossible without it
#   2. TOOL CALLING       -> Task 10 (the interrogation panel) cannot exist without it
#   3. translation quality-> Task 11 (vernacular feedback) degrades without it
#
# Capability 2 is the reason this script exists. It is not a config question --
# it is "does the API do what the docs say", and the difference between learning
# that tonight and learning it at 15:00 is the whole feature.
#
# Usage, from the repo root:
#   set -a && . ./.env && set +a && ./scripts/check-sarvam.sh
#
# Prints no secrets. Safe to paste the output into a channel.
set -u

BASE="https://api.sarvam.ai/v1"
MODEL="sarvam-105b"   # Sarvam-M is deprecated and no longer served

if [ -z "${SARVAM_API_KEY:-}" ]; then
  echo "SARVAM_API_KEY is not set in this shell."
  echo "Run:  set -a && . ./.env && set +a && ./scripts/check-sarvam.sh"
  exit 2
fi
echo "key: set (${#SARVAM_API_KEY} chars)"
echo

req() {
  curl -sS --max-time 45 "$BASE/chat/completions" \
    -H "Authorization: Bearer $SARVAM_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$1"
}

# ---------------------------------------------------------------- 1. completion
echo "=== 1/3  auth + completion ============================================"
R1=$(req '{
  "model": "'"$MODEL"'",
  "messages": [
    {"role": "system", "content": "Reply with exactly the word READY and nothing else."},
    {"role": "user", "content": "Are you there?"}
  ],
  "max_tokens": 16
}')
printf '%s\n' "$R1" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print("FAIL  not JSON:", e); raise SystemExit
if "error" in d:
    print("FAIL ", json.dumps(d["error"])[:300]); raise SystemExit
c=(d.get("choices") or [{}])[0]
print("PASS  content:", repr((c.get("message") or {}).get("content","")[:60]))
print("      finish_reason:", c.get("finish_reason"))
u=d.get("usage") or {}
print("      usage:", {k:u.get(k) for k in ("prompt_tokens","completion_tokens","total_tokens")})
print("      NOTE: put those token counts in the cost meter. If usage is absent,")
print("            the cost meter has to estimate and the deck must say so.")
'
echo

# --------------------------------------------------------------- 2. tool calls
echo "=== 2/3  TOOL CALLING (the one that matters) =========================="
R2=$(req '{
  "model": "'"$MODEL"'",
  "messages": [
    {"role": "system", "content": "You have no data of your own. Use the tool to answer. Never state a figure you did not receive from a tool."},
    {"role": "user", "content": "What is the on-time arrival for vendor V07 this week?"}
  ],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_metric",
      "description": "Read one metric for one slice over the current window, with its reference points.",
      "parameters": {
        "type": "object",
        "properties": {
          "metricId":  {"type": "string", "enum": ["ota", "otd", "vendor_ota", "sla_breach"]},
          "dimension": {"type": "string", "enum": ["VENDOR", "SITE", "SHIFT", "MODE", "DIRECTION", "NONE"]},
          "value":     {"type": "string", "description": "the dimension value; omit when dimension is NONE"}
        },
        "required": ["metricId", "dimension"]
      }
    }
  }],
  "tool_choice": "auto",
  "max_tokens": 256
}')
printf '%s\n' "$R2" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print("FAIL  not JSON:", e); raise SystemExit
if "error" in d:
    print("FAIL ", json.dumps(d["error"])[:400])
    print("      If this says tools/tool_choice is unsupported, TOOL CALLING IS OUT.")
    print("      Tell the team tonight: Task 10 and the interrogation panel are cut,")
    print("      and the demo script loses its last beat. Everything else stands.")
    raise SystemExit
c=(d.get("choices") or [{}])[0]
fr=c.get("finish_reason"); msg=c.get("message") or {}
tc=msg.get("tool_calls") or []
print("      finish_reason:", fr)
if fr=="tool_calls" and tc:
    f=tc[0].get("function") or {}
    print("PASS  tool:", f.get("name"), " args:", f.get("arguments"))
    try:
        a=json.loads(f.get("arguments") or "{}")
        ok = a.get("metricId") in ("ota","otd","vendor_ota","sla_breach") and a.get("dimension") in ("VENDOR","SITE","SHIFT","MODE","DIRECTION","NONE")
        print("      args respect the enums:", ok, "->", a)
        if not ok:
            print("      NOTE: it invented an argument value. The tools validate before")
            print("            executing and refuse by name, so this is handled -- but")
            print("            expect a retry loop and keep MAX_TOOL_CALLS at 4.")
    except Exception as e:
        print("      args are not valid JSON:", e, "-- parse defensively in tools.py")
else:
    print("FAIL  no tool_calls. It answered in prose instead:")
    print("     ", repr((msg.get("content") or "")[:200]))
    print("      Try tool_choice as {\"type\":\"function\",\"function\":{\"name\":\"get_metric\"}}")
    print("      to force it. If forcing also fails, tool calling is out -- see above.")
'
echo

# --------------------------------------------------------------- 3. translation
echo "=== 3/3  translation (Indic -> English) ==============================="
R3=$(req '{
  "model": "'"$MODEL"'",
  "messages": [
    {"role": "system", "content": "Translate the employee transport feedback into English. Reply with the translation only, no commentary."},
    {"role": "user", "content": "Cab bahut late tha, koi soochna nahi mili"}
  ],
  "max_tokens": 64
}')
printf '%s\n' "$R3" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception as e: print("FAIL  not JSON:", e); raise SystemExit
if "error" in d:
    print("FAIL ", json.dumps(d["error"])[:300]); raise SystemExit
t=((d.get("choices") or [{}])[0].get("message") or {}).get("content","").strip()
print("PASS  translation:", repr(t[:120]))
low=t.lower()
hits=[w for w in ("late","delay","no update","not inform","no inform","information") if w in low]
print("      lexicon markers found:", hits or "NONE")
if not hits:
    print("      NOTE: the sentiment lexicon scores the TRANSLATED text, so if the")
    print("            wording never matches a marker, experience scores neutral.")
    print("            Widen SENTIMENT_LEXICON to match what Sarvam actually returns")
    print("            -- do not hand-tune the translation.")
'
echo
echo "=== verdict ==========================================================="
echo "1 PASS -> the brief can be model-composed (Task 6)."
echo "2 PASS -> the interrogation panel is viable (Task 10). 2 FAIL -> cut it tonight."
echo "3 PASS -> vernacular feedback is viable (Task 11)."
echo
echo "Also note the credit balance in the Sarvam dashboard while you are there."
