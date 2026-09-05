"""The shape of a shift plan. One Pydantic model, shared by the LangChain
parser, the deterministic fallback and the Slack formatter -- so a plan
written by the model and a plan written without one render identically."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ShiftBlock(BaseModel):
    window: str = Field(description="Local clock window, e.g. '08:00-11:00'")
    band: str = Field(description="EARLY / DAY / EVENING / NIGHT")
    direction: str = Field(description="LOGIN, LOGOUT or MIXED")
    vehicles: int = Field(description="Cabs to keep rostered in this block")
    drivers: int = Field(description="Drivers to roster in this block")
    expected_trips: float = Field(description="Forecast trips in this block")
    expected_employees: float = Field(description="Forecast employees in this block")
    note: str = Field(default="", description="One short operational note")


class ShiftPlan(BaseModel):
    headline: str = Field(description="One line the manager reads first")
    expected_demand: str = Field(description="Forecast demand in one or two sentences")
    peak_periods: list[str] = Field(default_factory=list,
                                    description="Peak windows and why they matter")
    shift_blocks: list[ShiftBlock] = Field(default_factory=list,
                                           description="The roster itself")
    capacity_risks: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list,
                                 description="Risks or oddities in the data or the day")
    eta_considerations: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list,
                                           description="What to do before the first shift")
    reasoning: str = Field(default="", description="Brief reasoning behind the plan")
