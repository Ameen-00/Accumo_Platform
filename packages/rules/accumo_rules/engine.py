from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass
class Finding:
    amount_at_risk: Decimal
    currency: str
    confidence: Decimal
    title: str
    explanation: dict[str, Any]
    evidence: dict[str, Any]
    fingerprint_parts: list[str] = field(default_factory=list)


class Rule(Protocol):
    code: str
    default_params: dict[str, Any]

    def run(self, ctx: Any, params: dict[str, Any]) -> Iterator[Finding]: ...
