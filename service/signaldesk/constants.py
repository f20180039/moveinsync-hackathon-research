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

# Verdict bands, as a fraction of the reference, ONE SET PER DIRECTION --
# fix round 1 of Task 5's review. A single scalar CONCERN_MAX (fix round 0's
# 0.05/0.30/1.90) made BREACH structurally unreachable for 3 of the 4 active
# metrics: verdict.delta() SATURATES AT 1.0 for a HIGHER-is-better metric
# (shortfall = reference - observed <= reference when observed >= 0), so
# ota/otd/vendor_ota can never exceed d=1.0 -- a CONCERN_MAX of 1.90, tuned
# for LOWER-is-better no_show_rate (whose peer medians are themselves only a
# few percent, so its deltas are genuinely unbounded), left every HIGHER
# finding capped at CONCERN forever. Every BREACH fix round 0 measured was
# no_show_rate; that was the bug, not a coincidence.
#
# Keyed by Direction.value (a plain str, "HIGHER"/"LOWER") rather than the
# Direction enum itself: schemas.py's `from . import constants` (its own
# line 8) executes BEFORE schemas.py defines `class Direction` (line 34), so
# a module-level `from .schemas import Direction` here would create a real
# circular import the moment anything imports schemas.py before constants.py
# -- which happens in practice (api.py -> ingest.py -> schemas.py, all before
# registry.py's `from . import constants` ever runs). Confirmed by an
# isolated repro during this fix. verdict.tier_for() selects a direction's
# tuple via `C.BANDS[better.value]`.
#
# MEASURED against data/real (615k trips), late-July week
# 2026-07-25..2026-07-31, Tier 1 metrics x every slice, 210 metric x slice
# pairs with a resolvable reference (156 HIGHER: ota/otd/vendor_ota; 54
# LOWER: no_show_rate).
#
# BEFORE (single scalar 0.05/0.30/1.90): ALL 210 findings PASS 104 / WATCH 56
# / CONCERN 40 / BREACH 10 -- every one of the 10 BREACHes is no_show_rate;
# 0 of the 156 HIGHER findings ever reach BREACH, structurally, since their
# single worst measured delta (0.8564) is already below the old CONCERN_MAX
# (1.90).
#
# AFTER, HIGHER (ota/otd/vendor_ota), bands (0.05, 0.20, 0.75):
#   ALL 156:            PASS 90 / WATCH 40 / CONCERN 22 / BREACH 4
#   overall+vendor (71 of 156): PASS 43 / WATCH 19 / CONCERN 7 / BREACH 2
#   All four tiers present; the worst vendor by vendor_ota (Pooja Sokolov
#   Travel, 9.78% against a peer median in the 42-50% range across 23
#   vendors measured, p75=50.42) BREACHES on both `ota` (d=0.8475) and
#   `vendor_ota` itself (d=0.7984) -- criterion (b) satisfied at BREACH, not
#   merely CONCERN, so a vendor at the bottom of the real spread demonstrably
#   CAN reach it. 2 BREACHes at the overall+vendor level, within 1-5.
#
# AFTER, LOWER (no_show_rate; cost_per_km checked independently below, not
# yet a Tier 1 metric), bands (0.05, 0.30, 2.00):
#   ALL 54:             PASS 14 / WATCH 8 / CONCERN 23 / BREACH 9
#   overall+vendor (24 of 54): PASS 2 / WATCH 4 / CONCERN 13 / BREACH 5
#   2.00 is the HONEST concern band here, not a nudged one: no_show_rate's
#   real spread reaches deltas of 1.0-7.1 because some sites/vendors have a
#   peer median near zero, so a smaller CONCERN_MAX turns the whole metric
#   into a wall (checked at 0.75, the HIGHER value: 30 of 54 would BREACH).
#   5 BREACHes at the overall+vendor level ("about five"), NOT nudged for
#   any test's benefit -- if it had measured to something other than 5, it
#   would be that number. Independently checked against cost_per_km (not
#   yet Tier 1, same LOWER direction, same bands, same real window): its
#   spread is even wider (site Denver Office d=29.6, tenant vanta-Sea
#   d=28.7, vendor Isha Mikhailov Travel d=24.2, vendor Aarav Petrov Travel
#   d=15.4, vendor Priya Mikhailov Travel d=4.5) -- CONCERN_MAX=2.00 still
#   separates exactly those 5 genuine outliers from the rest rather than
#   flagging everything, on a second LOWER metric it was not tuned against.
#
# AFTER, on data/sample (the fast-test dataset), same bands, late-July week,
# for the record (NOT used to choose either band -- see tests/test_sweep.py):
#   ALL 197: PASS 97 / WATCH 22 / CONCERN 63 / BREACH 15. All four tiers
#   present and 10 vendor_ota findings are CONCERN-or-worse, both without any
#   adjustment aimed at the sample.
BANDS: dict[str, tuple[float, float, float]] = {
    "HIGHER": (0.05, 0.20, 0.75),
    "LOWER": (0.05, 0.30, 2.00),
}

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
