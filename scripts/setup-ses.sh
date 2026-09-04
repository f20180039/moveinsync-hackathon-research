#!/bin/sh
# Request SES sandbox verification for the sender and every recipient, then
# report status. Idempotent and re-runnable: run it once to send the requests,
# then again after people click, to confirm.
#
# Usage, from the repo root:
#   set -a && . ./.env && set +a && ./scripts/setup-ses.sh
#
# Reads SES_FROM, SES_TO (comma-separated) and AWS_REGION from the environment.
# Prints addresses (not secrets) -- safe to paste into a channel.
#
# Two things that silently break this:
#   1. Identities are PER REGION. Verify in the same region the service sends
#      from, or every send fails with "Email address not verified" while the
#      console shows the address as verified -- in a different region.
#   2. In sandbox you can only send TO verified addresses AND FROM a verified
#      address. The sender is easy to forget.
set -u

REGION="${AWS_REGION:-ap-south-1}"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found. brew install awscli"
  exit 2
fi

echo "region: $REGION"
if ! IDENT=$(aws sts get-caller-identity --query Account --output text 2>&1); then
  echo "FAIL  no working AWS credentials:"
  echo "      $IDENT"
  echo "      Fix that first -- 'aws configure' or your SSO login. This is the"
  echo "      other tonight item with human latency: if the account needs an"
  echo "      owner's approval, you want to know now, not at 13:30."
  exit 1
fi
echo "account: $IDENT"
echo

if [ -z "${SES_FROM:-}" ] || [ -z "${SES_TO:-}" ]; then
  echo "SES_FROM and/or SES_TO are not set."
  echo "Add them to .env first, e.g."
  echo "  SES_FROM=you@yourdomain.com"
  echo "  SES_TO=teammate1@x.com,teammate2@y.com"
  exit 2
fi

# Sender first, then each recipient. Deduplicated, since the sender is often
# also a recipient.
ALL=$(printf '%s,%s' "$SES_FROM" "$SES_TO" | tr ',' '\n' \
      | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | sort -u)

echo "=== requesting verification ==========================================="
for addr in $ALL; do
  case "$addr" in
    *@*.*) ;;
    *) echo "  SKIP  $addr  (does not look like an email address)"; continue ;;
  esac
  if out=$(aws ses verify-email-identity --email-address "$addr" \
             --region "$REGION" 2>&1); then
    echo "  sent  $addr"
  else
    echo "  FAIL  $addr"
    echo "        $out"
  fi
done
echo
echo "Each address now has a mail from AWS titled"
echo '  "Amazon Web Services - Email Address Verification Request"'
echo "The link inside EXPIRES IN 24 HOURS and must be clicked by the owner of"
echo "the address. Tell them to check spam -- Gmail and Outlook often file it"
echo "there. Re-running this script re-sends to anyone still pending."
echo

echo "=== current status ===================================================="
aws ses get-identity-verification-attributes \
  --identities $ALL --region "$REGION" --output json 2>/dev/null \
| python3 -c '
import json, sys
try:
    d = json.load(sys.stdin).get("VerificationAttributes", {})
except Exception:
    print("  could not read status; try the console for region above"); raise SystemExit
if not d:
    print("  no identities returned yet -- give it a few seconds and re-run")
    raise SystemExit
pending = 0
for addr, a in sorted(d.items()):
    s = a.get("VerificationStatus", "?")
    mark = "OK  " if s == "Success" else "WAIT"
    if s != "Success":
        pending += 1
    print(f"  {mark}  {addr:<40} {s}")
print()
if pending:
    print(f"  {pending} still pending. Nothing can be emailed to a pending address.")
    print("  Chase the clicks, then re-run this script to confirm.")
else:
    print("  All verified. SES is closed out -- add SES_FROM/SES_TO to .env and")
    print("  the email channel will start reporting delivered=true.")
'
echo
echo "=== sandbox limits, for the record ===================================="
# No python here on purpose: an f-string with escaped quotes inside a
# single-quoted shell block is a syntax error, and it was one. The CLI's own
# --query does this without the quoting hazard.
aws ses get-send-quota --region "$REGION" \
    --query '[Max24HourSend,MaxSendRate,SentLast24Hours]' --output text 2>/dev/null \
  | awk '{printf "  %s sends/24h, %s/sec, %s used\n", $1, $2, $3}' \
  || echo "  (quota unavailable -- informational only, ignore)"
echo "  Ample. The demo sends a handful."
echo

echo "Note: leaving the sandbox is NOT achievable for tomorrow -- it needs SPF,"
echo "DKIM and DMARC in place BEFORE the request can be filed, then 4-24h of"
echo "review. Sandbox delivery to verified addresses IS the email proof, and"
echo "that is a deliberate decision, not a limitation to apologise for."
