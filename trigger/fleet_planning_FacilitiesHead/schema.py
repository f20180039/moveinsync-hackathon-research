"""The shape of a next-week fleet plan. One Pydantic model, shared by the
LangChain parser, the deterministic fallback and the Slack formatter -- so a
plan written by the model and one written without a model render identically.

Note what is NOT in here: no rider counts, no vehicle counts, no deltas. Every
figure is computed in stats.py and rendered by format.py straight from that
dict. The model is given the finished table and asked for prose ABOUT it; if
it were allowed to carry the numbers, a hallucinated vehicle count would reach
a Facilities Head as an instruction.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BandCall(BaseModel):
    day: str = Field(description="YYYY-MM-DD")
    band: str = Field(description="EARLY / DAY / EVENING / NIGHT")
    direction: str = Field(description="ADD, RELEASE or HOLD")
    why: str = Field(default="", description="One short operational reason")


class FleetPlan(BaseModel):
    headline: str = Field(description="One line the Facilities Head reads first")
    demand_outlook: str = Field(description="Next week's demand shape, one or two sentences")
    add_where: list[str] = Field(default_factory=list,
                                 description="Where to add vehicles, and why")
    release_where: list[str] = Field(default_factory=list,
                                     description="Where to release vehicles, and why")
    band_calls: list[BandCall] = Field(default_factory=list)
    evidence_caveats: list[str] = Field(
        default_factory=list,
        description="Thin basis days, screened anomalies, withheld days")
    recommended_actions: list[str] = Field(default_factory=list,
                                           description="What to do before Monday")
    reasoning: str = Field(default="", description="Brief reasoning behind the plan")
