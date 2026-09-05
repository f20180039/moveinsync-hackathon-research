"""The model layer's whole surface. It produces language; it never produces a
figure and never sees a raw row."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from openai import OpenAI

from . import constants as C

BASE_URL = "https://api.sarvam.ai/v1"
MODEL = "sarvam-105b"      # Sarvam-M is deprecated and no longer served


class TruncatedResponse(RuntimeError):
    """The model hit its token ceiling or returned nothing.

    Raised rather than returned so every caller must decide. SarvamComposer
    catches it and sends the template brief; the interrogator catches it and
    withholds. Silently returning a half-written brief is the one outcome
    neither of them should have to guess at.
    """


@dataclass
class CostMeter:
    """Tokens and rupees per interaction, extrapolated to scale.

    The architecture is what makes this number good: ONE model call per brief
    rather than one per row, so tokens stay flat as row counts grow. That is the
    cost-at-scale story, and it is now a figure on screen rather than a claim.
    """
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_purpose: dict[str, int] = field(default_factory=dict)

    def record(self, purpose: str, usage) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
        self.output_tokens += getattr(usage, "completion_tokens", 0) or 0
        self.by_purpose[purpose] = self.by_purpose.get(purpose, 0) + 1

    @property
    def inr(self) -> float:
        return (self.input_tokens / 1000 * C.INR_PER_1K_INPUT_TOKENS
                + self.output_tokens / 1000 * C.INR_PER_1K_OUTPUT_TOKENS)

    @property
    def inr_per_org_per_month(self) -> float:
        """The figure that makes the argument: cost per ORGANISATION, not per
        employee, because the model sees aggregates rather than rows.

        Measured against the real rate, one brief is ~1,900 tokens ~ Rs 0.09;
        three audiences daily is ~Rs 8/month -- and that total is FLAT whether
        the client has 500 employees or 50,000. Per-employee cost therefore
        falls as the client grows, which is the opposite of how a per-row
        pipeline behaves.
        """
        if not self.calls:
            return 0.0
        return self.inr / self.calls * 3 * 30

    def snapshot(self) -> dict:
        per_call = (self.input_tokens + self.output_tokens) / self.calls if self.calls else 0
        org_month = self.inr_per_org_per_month
        return {
            "calls": self.calls,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "tokensPerCall": round(per_call),
            "inr": round(self.inr, 4),
            "inrPerOrgPerMonth": round(org_month, 2),
            "employeesAtScale": C.EMPLOYEES_AT_SCALE,
            # The number that carries the argument: per-employee cost FALLS as
            # the client grows, because one brief covers the whole org.
            "inrPerEmployeePerMonth": round(org_month / C.EMPLOYEES_AT_SCALE, 6),
            "byPurpose": dict(self.by_purpose),
            "pricingConfigured": C.INR_PER_1K_INPUT_TOKENS > 0,
            # Rs 0.03/629 tokens is a rounded dashboard figure: +/-17%. Show
            # "fractions of a rupee", never three significant figures.
            "rateIsApproximate": True,
        }


COST = CostMeter()


class SarvamClient:
    """Sarvam's API is OpenAI-compatible, so the official SDK is used with a
    base_url override.

    No retry, no backoff, no circuit breaker: explicitly out of scope. A failed
    call degrades to the template brief, which is a better answer than a slow one.
    """

    def __init__(self, api_key: str | None = None):
        self._client = OpenAI(api_key=api_key or os.environ.get("SARVAM_API_KEY", ""),
                              base_url=BASE_URL)

    # MEASURED 2026-09-04: sarvam-105b bills reasoning tokens as
    # completion_tokens without surfacing them in message.content. Replying with
    # the single word "READY" cost 195 completion tokens; one tool call cost
    # 199; a ten-word translation cost 19. So the overhead is real, variable,
    # and up to ~200 tokens BEFORE any prose. A 700-token ceiling on a
    # 200-word brief is uncomfortably close to truncating.
    DEFAULT_MAX_TOKENS = 1600

    def complete(self, messages: list[dict], purpose: str = "brief",
                 max_tokens: int | None = None) -> str:
        r = self._client.chat.completions.create(
            model=MODEL, messages=messages,
            max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS)
        if r.usage:
            COST.record(purpose, r.usage)
        choice = r.choices[0]
        text = (choice.message.content or "").strip()

        # A truncated brief is the DANGEROUS failure, not an obvious one: half a
        # sentence whose every figure is correct passes the numeric validator
        # and goes on stage mid-word. Treat it as a hard failure so the caller
        # falls back to the deterministic template.
        if choice.finish_reason == "length":
            raise TruncatedResponse(
                f"{purpose} hit the {max_tokens or self.DEFAULT_MAX_TOKENS}-token "
                f"ceiling; reasoning overhead is billed but not returned")
        if not text:
            raise TruncatedResponse(f"{purpose} returned empty content "
                                    f"(finish_reason={choice.finish_reason})")
        return text
