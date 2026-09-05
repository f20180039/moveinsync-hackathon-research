"""One escalation, as the model must return it and as Slack renders it."""
from __future__ import annotations

from pydantic import BaseModel, Field

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
ATTENTION = ("Informational", "Potential issue", "Requires attention",
             "Immediate escalation")


class Escalation(BaseModel):
    ride_id: str = Field(description="The ride this is about")
    issue_type: str = Field(description="Short label, e.g. 'ETA deviation', "
                                        "'Late booking', 'Driver delay', "
                                        "'Multiple factors'")
    severity: str = Field(description="One of LOW, MEDIUM, HIGH, CRITICAL")
    requires_attention: str = Field(
        description="One of: Informational, Potential issue, "
                    "Requires attention, Immediate escalation")
    delay_minutes: int | None = Field(
        default=None, description="Minutes of delay, copied from the facts given")
    likely_cause: str = Field(description="One sentence on the most likely cause")
    reasoning: str = Field(description="Two sentences at most, citing the facts given")
    recommended_action: str = Field(
        description="One concrete thing the Team Manager should do now")
