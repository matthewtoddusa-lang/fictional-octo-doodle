"""Pluggable decision engine.

Replace the body of :func:`decide` (or monkey-patch / import your own function in
``main.py``) to wire in an external model. The contract is fixed:

    decide(state: dict) -> {"action": "buy" | "hold" | "skip", "confidence": float}

``state`` is built by :func:`memecoin_bot.monitor.build_state` and is JSON-serialisable.
An optional ``"reason"`` key in the result is shown on the dashboard.
"""
from __future__ import annotations

from typing import Callable

VALID_ACTIONS = ("buy", "hold", "skip")

DecideFn = Callable[[dict], dict]


def decide(state: dict) -> dict:
    """STUB: always skips. Wire your external model in here."""
    return {"action": "skip", "confidence": 0.0, "reason": "decision engine not implemented"}


def validate_decision(result: object) -> dict:
    """Normalise whatever the engine returned; anything malformed becomes a safe skip."""
    if not isinstance(result, dict):
        return {"action": "skip", "confidence": 0.0, "reason": "engine returned non-dict"}
    action = result.get("action")
    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = float("nan")
    if action not in VALID_ACTIONS or not 0.0 <= confidence <= 1.0:
        return {"action": "skip", "confidence": 0.0, "reason": f"invalid engine output: {result!r}"[:120]}
    return {"action": action, "confidence": confidence, "reason": str(result.get("reason", ""))}
