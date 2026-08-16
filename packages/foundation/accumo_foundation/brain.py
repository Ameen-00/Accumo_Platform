"""Optional SpaceXAI explainer. Never decides. Never marks money saved.

If XAI_API_KEY is missing the product still runs — rules stay deterministic.
"""

from __future__ import annotations

import os
from typing import Any


SYSTEM = (
    "You are Pulse, Accumo's payment-integrity reviewer. "
    "Explain a finding in two short sentences a business owner can act on. "
    "Do not invent invoice numbers, GSTINs, or amounts. "
    "Do not say money is saved or recovered. "
    "If the evidence is thin, say Needs human. "
    "Never give legal, tax, or audit advice."
)


def brief_run(briefing: dict[str, Any]) -> str | None:
    """Optional rewrite of the Start-here card. Never invents counts or money."""
    key = os.environ.get("XAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    try:
        client = OpenAI(api_key=key, base_url="https://api.x.ai/v1")
        resp = client.responses.create(
            model="grok-4.5",
            input=[
                {
                    "role": "system",
                    "content": (
                        "Rewrite this Pulse briefing in four short sentences a first-time user can follow. "
                        "Keep every number exactly. Do not add findings. Do not say money is saved. "
                        "End with: confirm what is real, dismiss what is not."
                    ),
                },
                {"role": "user", "content": str(briefing)},
            ],
        )
        text = (resp.output_text or "").strip()
        return text or None
    except Exception:  # noqa: BLE001
        return None


def explain_finding(finding: dict[str, Any]) -> str | None:
    key = os.environ.get("XAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(api_key=key, base_url="https://api.x.ai/v1")
    payload = {
        "title": finding.get("title"),
        "rule": finding.get("rule_code") or finding.get("rule"),
        "amount": finding.get("amount_at_risk"),
        "explanation": finding.get("explanation"),
    }
    try:
        resp = client.responses.create(
            model="grok-4.5",
            input=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": str(payload)},
            ],
        )
        text = (resp.output_text or "").strip()
        return text or None
    except Exception:  # noqa: BLE001 — explainer must never break a review
        return None
