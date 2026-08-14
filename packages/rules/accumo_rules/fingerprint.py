"""Stable id for an exception across re-runs. Built from facts, not from the run."""

from __future__ import annotations

import hashlib


def fingerprint(rule_code: str, *parts: str) -> str:
    payload = "|".join([rule_code, *sorted(str(p) for p in parts)])
    return hashlib.sha256(payload.encode()).hexdigest()
