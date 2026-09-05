"""Structured LLM output for the three levels. The model fills prose fields;
every figure in the final Slack report is rendered from `metrics.py`, so no
schema here carries a number the model could get wrong."""
from __future__ import annotations

from pydantic import BaseModel, Field

STATUSES = ("GOOD", "WATCH", "NEEDS ATTENTION")


class VendorConcern(BaseModel):
    vendor: str
    concern: str = Field(description="What is wrong, in one sentence")
    action: str = Field(description="One thing to do about it")


class DailyBrief(BaseModel):
    overall_status: str = Field(description="GOOD, WATCH or NEEDS ATTENTION")
    headline: str = Field(description="One line the Facilities Head reads first")
    what_went_well: list[str] = Field(default_factory=list)
    what_went_poorly: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list,
                                 description="Anything unusual against the day's own peers")
    vendors_needing_attention: list[VendorConcern] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class VendorNote(BaseModel):
    vendor: str
    note: str = Field(description="One sentence on why this vendor is here")


class MonthlyReview(BaseModel):
    overall_status: str = Field(description="GOOD, WATCH or NEEDS ATTENTION")
    headline: str
    best_performers: list[VendorNote] = Field(default_factory=list)
    underperformers: list[VendorNote] = Field(default_factory=list)
    improving: list[VendorNote] = Field(default_factory=list)
    deteriorating: list[VendorNote] = Field(default_factory=list)
    cost_observations: list[str] = Field(
        default_factory=list, description="Value-for-money reading, or the "
                                          "limitation if cost data is thin")
    systemic_vs_isolated: str = Field(
        default="", description="Whether this month's problems look systemic "
                                "across vendors or isolated to a few")
    management_actions: list[str] = Field(default_factory=list)


class VendorStrategy(BaseModel):
    """One vendor's quarterly verdict -- the heart of the strategic review."""
    vendor: str
    overall_assessment: str = Field(description="Two sentences at most")
    recommendation: str = Field(
        description="EXACTLY one of: CONTINUE — INCREASE ALLOCATION, "
                    "CONTINUE — PREFERRED, CONTINUE, "
                    "CONTINUE — PERFORMANCE MONITORING, REVIEW CONTRACT, "
                    "REDUCE ALLOCATION, CONSIDER REPLACEMENT")
    confidence: str = Field(description="HIGH, MEDIUM or LOW")
    key_strengths: list[str] = Field(default_factory=list)
    key_concerns: list[str] = Field(default_factory=list)
    value_for_money: str = Field(
        description="Cost against service delivered. Say plainly if cost data "
                    "does not support a conclusion.")
    performance_trend: str = Field(description="What moved across the quarter, and which way")
    recommended_action: str = Field(description="One concrete next step")
    evidence: list[str] = Field(default_factory=list,
                                description="The facts behind the recommendation")


class NextQuarterStrategy(BaseModel):
    increase_allocation: list[str] = Field(default_factory=list)
    maintain: list[str] = Field(default_factory=list)
    monitor: list[str] = Field(default_factory=list)
    commercial_review: list[str] = Field(default_factory=list)
    potential_replacement: list[str] = Field(default_factory=list)


class QuarterExecutive(BaseModel):
    overall_status: str = Field(description="GOOD, WATCH or NEEDS ATTENTION")
    key_finding: str = Field(description="The single most important thing this quarter, "
                                         "with the evidence for it")
    best_performer: str
    best_value_for_money: str
    vendor_requiring_review: str
    strategic_risks: list[str] = Field(default_factory=list)
    next_quarter_strategy: NextQuarterStrategy = Field(default_factory=NextQuarterStrategy)
    top_reasons: list[str] = Field(default_factory=list,
                                   description="The 3-5 reasons behind this strategy")
    confidence: str = Field(default="MEDIUM", description="HIGH, MEDIUM or LOW")
