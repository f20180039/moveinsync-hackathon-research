"""Solution 3 -- Facilities Head: vendor strategy.

Three separate triggers over the same deterministic metric engine:

    daily/      end of day      operational health
    monthly/    month end       performance review + scorecards
    quarterly/  quarter end     strategy: continue / review / reduce / replace

Entry points:
    python -m trigger.vendor_strategy_Facilities_Head.daily.run
    python -m trigger.vendor_strategy_Facilities_Head.monthly.run
    python -m trigger.vendor_strategy_Facilities_Head.quarterly.run
"""
