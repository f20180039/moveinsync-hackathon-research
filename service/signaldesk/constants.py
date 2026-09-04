"""The thresholds the spec names its metrics for but never defines.

One place, so the real dataset can move them in one edit at 10:30.
"""

# Deviation 4: the spec names on-time arrival and SLA breach but defines neither.
ON_TIME_GRACE_MS = 5 * 60_000
SLA_BREACH_MS = 15 * 60_000

# Deviation 8: epoch ms are absolute; "night trip" is local.
IST_OFFSET_MS = 19_800_000

# MoveInSync calls this window "dark hours" and configures it PER CITY. Their
# published example is 19:00-06:00, so 19 is the default here — an earlier draft
# guessed 22:00 and was three hours too narrow. Per-site override is the honest
# multi-tenancy story and is nearly free, since it is already one dict.
# See docs/moveinsync-domain-vocabulary.md §1.
DARK_HOURS_DEFAULT = (19, 6)
DARK_HOURS_BY_SITE: dict[str, tuple[int, int]] = {}


def dark_hours(site: str | None = None) -> tuple[int, int]:
    return DARK_HOURS_BY_SITE.get(site or "", DARK_HOURS_DEFAULT)

# Verdict bands, as a fraction of the reference. PROVISIONAL until Task 5
# measures them against the real dataset (spec §6.3 requires this).
PASS_MAX = 0.02
WATCH_MAX = 0.05
CONCERN_MAX = 0.15

# Below this, no tier above WATCH may be emitted.
MIN_TRUSTED_CONFIDENCE = 0.5
# Below this, the narrative must disclose the uncertainty.
DISCLOSE_CONFIDENCE_BELOW = 0.9

# Sarvam pricing for the cost meter.
#
# MEASURED 2026-09-04 from the Sarvam dashboard: 629 tokens billed at Rs 0.03,
# i.e. ~Rs 0.048 per 1k tokens blended (~Rs 48 per million).
#
# Two honest caveats that belong on the slide, not just in this comment:
#   1. Rs 0.03 is the dashboard's rounded display, so the true rate is somewhere
#      in Rs 0.040-0.056 per 1k. That is +/-17%, which is fine for "fractions of
#      a rupee" and NOT fine for quoting three significant figures.
#   2. It is a BLENDED rate. We do not have the input/output split, so both
#      constants below carry the same value. If Sarvam publishes separate
#      figures, use those instead of this measurement.
INR_PER_1K_INPUT_TOKENS = 0.048
INR_PER_1K_OUTPUT_TOKENS = 0.048
EMPLOYEES_AT_SCALE = 5_000

# Reasoning tokens ARE billed even when content comes back empty -- the 629
# tokens above were spent on three calls that returned nothing, truncated by a
# max_tokens that was too low. If the API reports reasoning tokens separately,
# the cost meter must add them, or it will under-report.
COUNT_REASONING_TOKENS = True
