"""Heuristic risk score (0 = safest, 100 = riskiest) and threshold gating.

The scoring is a deliberately simple placeholder; the real judgement is expected to come
from the decision engine. The thresholds in ``Config`` are enforced *after* the engine
runs, so a model can never bypass them.
"""
from __future__ import annotations

from .chain import TokenInfo
from .config import Config


def risk_score(token: TokenInfo, liquidity: int, initialized: bool) -> float:
    if not token.has_code:
        return 100.0
    score = 0.0
    if token.owner_renounced is False:
        score += 35  # live owner can usually mint / pause / change fees
    if token.total_supply in (None, 0):
        score += 25
    if token.decimals is None or token.symbol is None:
        score += 15  # not a well-formed ERC-20
    if not initialized:
        score += 15
    if liquidity <= 0:
        score += 10
    return min(score, 100.0)


def apply_thresholds(decision: dict, state: dict, cfg: Config) -> dict:
    """Downgrade a 'buy' to 'skip' if it violates any configured risk threshold."""
    if decision["action"] != "buy":
        return decision
    problems = []
    if decision["confidence"] < cfg.min_confidence:
        problems.append(f"confidence {decision['confidence']:.2f} < {cfg.min_confidence:.2f}")
    if state["liquidity"] < cfg.min_liquidity:
        problems.append(f"liquidity {state['liquidity']} < {cfg.min_liquidity}")
    if state["risk_score"] > cfg.max_risk_score:
        problems.append(f"risk {state['risk_score']:.0f} > {cfg.max_risk_score:.0f}")
    if state.get("price") is None:
        problems.append("no price")
    if problems:
        return {**decision, "action": "skip", "reason": "blocked: " + "; ".join(problems)}
    return decision
