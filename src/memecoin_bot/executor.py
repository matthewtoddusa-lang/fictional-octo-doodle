"""Trade executors. Only paper trading is implemented; real swaps are a stub."""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Position:
    pool: str
    token: str
    symbol: str | None
    entry_price: float  # quote-token units per memecoin
    size: float  # quote-token units spent
    confidence: float
    opened_at: float = field(default_factory=time.time)  # unix seconds
    mode: str = "paper"


class Executor(ABC):
    """Interface for anything that acts on a 'buy' decision."""

    @abstractmethod
    def buy(self, state: dict, decision: dict) -> Position | None:
        """Act on a buy. Return the opened Position, or None if nothing was done."""


class PaperExecutor(Executor):
    """Records simulated positions in memory and appends them to a JSONL file."""

    def __init__(self, position_size: float, positions_file: str | None = None):
        self.position_size = position_size
        self.positions: list[Position] = []
        self._path = Path(positions_file) if positions_file else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def buy(self, state: dict, decision: dict) -> Position | None:
        if any(p.pool == state["pool"] for p in self.positions):
            return None  # already holding this pool
        price = state.get("price")
        if price is None or price <= 0:
            return None
        pos = Position(
            pool=state["pool"],
            token=state["token"],
            symbol=state.get("symbol"),
            entry_price=price,
            size=self.position_size,
            confidence=decision["confidence"],
        )
        self.positions.append(pos)
        if self._path:
            with self._path.open("a") as f:
                f.write(json.dumps(asdict(pos)) + "\n")
        return pos


class LiveExecutor(Executor):
    """Placeholder for real on-chain swaps. Intentionally not implemented."""

    def buy(self, state: dict, decision: dict) -> Position | None:
        self._swap(state["token"], state["pool"], amount=0.0)
        return None

    def _swap(self, token: str, pool: str, amount: float) -> str:
        """TODO: build, sign and send a Uniswap V3 swap (router call, slippage, gas)."""
        raise NotImplementedError("Live trading is not implemented; use PaperExecutor.")
