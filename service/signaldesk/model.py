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

    Carries the usage figures (never the prompt) so the caller's fallback log
    line can say WHY -- prompt size, completion tokens spent, and the ceiling
    that was hit -- without that becoming the caller's job to re-derive.
    """

    def __init__(self, message: str, *, prompt_tokens: int | None = None,
                 completion_tokens: int | None = None, max_tokens: int | None = None):
        super().__init__(message)
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.max_tokens = max_tokens


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
    # and up to ~200 tokens BEFORE any prose on a TRIVIAL reply.
    #
    # MEASURED 2026-09-05 morning, on data/real (run-1785542400000-d0), the
    # SAME 543-prompt-token call (TRANSPORT_MANAGER, top 8 capped findings),
    # repeated:
    #   max_tokens=3200  -> completion_tokens=3200, finish_reason=length, 0 chars
    #   max_tokens=8000  -> completion_tokens=3473, finish_reason=stop,   1348 chars
    # -- an order of magnitude more overhead than the trivial reply above,
    # because it scales with the REASONING TASK (weighing 8 findings against
    # each other), not with prompt size.
    #
    # MEASURED 2026-09-05 later, from the field (a restarted service, two
    # consecutive requests): the SAME 543-token prompt burned completion_tokens
    # =6000 (the then-current ceiling) with ZERO content, TWICE. The one
    # earlier success (3473) was not the steady state.
    #
    # Two mitigations were tried and rejected before raising the ceiling
    # further, both measured with real calls against the same prompt:
    #   extra_body={"reasoning_effort": "low"}: 3 calls -> completion_tokens
    #     3192 (stop), 3044 (stop), 6000 (length, 0 chars). Better on average
    #     but still truncates -- does not "reliably finish under ~2,000
    #     tokens", so not adopted as a fix (it was not wired into production).
    #   extra_body={"reasoning_effort": "none"}: rejected by the API (400,
    #     "Input should be 'low', 'medium' or 'high'").
    #   extra_body={"thinking": {"type": "disabled"}}: accepted by the API
    #     (no error) but did not reduce anything -- 8000 (length, 0 chars),
    #     4585 (stop), 8000 (length, 0 chars) -- indistinguishable from doing
    #     nothing, so also not adopted.
    #
    # MEASURED 2026-09-05, 5 further real calls at max_tokens=16000, DEFAULT
    # settings, same prompt: completion_tokens 10545, 2096, 15427, 8686, 9293
    # (min 2096, max 15427; all finish_reason=stop). Latency ranged 15-103s
    # per call. CONCLUSION: the reasoning overhead for this model is not a
    # fixed or even a bounded-in-practice quantity -- it is unbounded-variable
    # and task-dependent, confirmed at n=13 real calls across three settings.
    # No ceiling can be picked with confidence that it will never be exceeded;
    # 16000 covers every call measured so far (with one at 96% of the
    # ceiling) but the NEXT call could still exceed it. Exceeding the ceiling
    # is SAFE -- compose.py falls back to the deterministic template -- it
    # only means the Sarvam-written brief does not reach the screen for that
    # request. compose._call_with_retry pairs this ceiling with exactly one
    # retry at double the ceiling (capped at 32000) for the same reason: a
    # single number cannot fix variance this size, but doubling once is cheap
    # (~Rs 0.30-1.50 per brief at these token counts) and turns most of the
    # observed truncations into a delivered narrative instead of a template.
    DEFAULT_MAX_TOKENS = 16000

    def complete(self, messages: list[dict], purpose: str = "brief",
                 max_tokens: int | None = None) -> str:
        r = self._client.chat.completions.create(
            model=MODEL, messages=messages,
            max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS)
        if r.usage:
            COST.record(purpose, r.usage)
        choice = r.choices[0]
        text = (choice.message.content or "").strip()

        ceiling = max_tokens or self.DEFAULT_MAX_TOKENS
        prompt_tokens = getattr(r.usage, "prompt_tokens", None) if r.usage else None
        completion_tokens = getattr(r.usage, "completion_tokens", None) if r.usage else None

        # A truncated brief is the DANGEROUS failure, not an obvious one: half a
        # sentence whose every figure is correct passes the numeric validator
        # and goes on stage mid-word. Treat it as a hard failure so the caller
        # falls back to the deterministic template.
        if choice.finish_reason == "length":
            raise TruncatedResponse(
                f"{purpose} hit the {ceiling}-token ceiling; reasoning overhead "
                f"is billed but not returned",
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                max_tokens=ceiling)
        if not text:
            raise TruncatedResponse(
                f"{purpose} returned empty content (finish_reason={choice.finish_reason})",
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                max_tokens=ceiling)
        return text

    def complete_message(self, messages: list[dict], tools: list[dict] | None = None,
                         purpose: str = "ask", max_tokens: int | None = None):
        """Like `complete()`, but for tool-calling (Task 9's interrogator):
        returns the raw response message (which may carry `.tool_calls`
        instead of, or alongside, `.content`) rather than requiring plain
        text. `compose.py`'s briefs never call tools, so `complete()` stays
        their whole surface -- this is tools.py's own entry point.

        Only a `finish_reason == "length"` (the ceiling truly hit mid-turn)
        raises TruncatedResponse; a `tool_calls` finish reason with no text
        content is the NORMAL shape of a turn that called a tool, not a
        failure."""
        kwargs = {"model": MODEL, "messages": messages,
                 "max_tokens": max_tokens or self.DEFAULT_MAX_TOKENS}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        r = self._client.chat.completions.create(**kwargs)
        if r.usage:
            COST.record(purpose, r.usage)
        choice = r.choices[0]
        ceiling = max_tokens or self.DEFAULT_MAX_TOKENS
        prompt_tokens = getattr(r.usage, "prompt_tokens", None) if r.usage else None
        completion_tokens = getattr(r.usage, "completion_tokens", None) if r.usage else None
        if choice.finish_reason == "length":
            raise TruncatedResponse(
                f"{purpose} hit the {ceiling}-token ceiling",
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                max_tokens=ceiling)
        return choice.message
