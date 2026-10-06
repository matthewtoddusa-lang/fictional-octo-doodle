"""Configuration loaded from environment variables / a .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
DEFAULT_CHAIN_ID = 4663
DEFAULT_FACTORY = "0x1f7d7550B1b028f7571E69A784071F0205FD2EfA"


@dataclass(frozen=True)
class Config:
    rpc_url: str = DEFAULT_RPC_URL
    chain_id: int = DEFAULT_CHAIN_ID
    factory_address: str = DEFAULT_FACTORY
    quote_tokens: frozenset[str] = field(default_factory=frozenset)  # lower-case

    poll_interval: float = 5.0
    start_block: int | None = None
    max_block_range: int = 2000
    max_pending_polls: int = 20

    min_liquidity: int = 1_000_000
    min_confidence: float = 0.7
    max_risk_score: float = 60.0

    position_size: float = 0.05
    positions_file: str = "data/positions.jsonl"

    @classmethod
    def from_env(cls, env_file: str | None = None) -> "Config":
        load_dotenv(env_file)  # no-op if the file doesn't exist
        g = os.environ.get

        def num(name: str, default, cast):
            raw = (g(name) or "").strip()
            if not raw:
                return default
            try:
                return cast(raw)
            except ValueError as exc:
                raise ValueError(f"Invalid value for {name}: {raw!r}") from exc

        quotes = frozenset(
            a.strip().lower() for a in (g("QUOTE_TOKENS") or "").split(",") if a.strip()
        )
        cfg = cls(
            rpc_url=(g("RPC_URL") or DEFAULT_RPC_URL).strip(),
            chain_id=num("CHAIN_ID", DEFAULT_CHAIN_ID, int),
            factory_address=(g("UNISWAP_V3_FACTORY") or DEFAULT_FACTORY).strip(),
            quote_tokens=quotes,
            poll_interval=num("POLL_INTERVAL_SECONDS", 5.0, float),
            start_block=num("START_BLOCK", None, int),
            max_block_range=num("MAX_BLOCK_RANGE", 2000, int),
            max_pending_polls=num("MAX_PENDING_POLLS", 20, int),
            min_liquidity=num("MIN_LIQUIDITY", 1_000_000, int),
            min_confidence=num("MIN_CONFIDENCE", 0.7, float),
            max_risk_score=num("MAX_RISK_SCORE", 60.0, float),
            position_size=num("PAPER_POSITION_SIZE", 0.05, float),
            positions_file=(g("POSITIONS_FILE") or "data/positions.jsonl").strip(),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.poll_interval <= 0:
            raise ValueError("POLL_INTERVAL_SECONDS must be > 0")
        if self.max_block_range < 1:
            raise ValueError("MAX_BLOCK_RANGE must be >= 1")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("MIN_CONFIDENCE must be between 0 and 1")
