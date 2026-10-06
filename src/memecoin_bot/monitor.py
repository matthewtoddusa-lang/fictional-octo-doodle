"""Glue: poll the factory, build a state dict per pool, run the engine, gate, execute."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .chain import ChainReader, PoolCreated
from .config import Config
from .decision import DecideFn, validate_decision
from .executor import Executor
from .risk import apply_thresholds, risk_score


def pick_target(ev: PoolCreated, quote_tokens: frozenset[str]) -> tuple[str, bool]:
    """Return (memecoin address, target_is_token0). Defaults to token0 if ambiguous."""
    t0q, t1q = ev.token0.lower() in quote_tokens, ev.token1.lower() in quote_tokens
    if t0q and not t1q:
        return ev.token1, False
    return ev.token0, True


def build_state(cfg: Config, reader: ChainReader, ev: PoolCreated) -> dict:
    target, is_t0 = pick_target(ev, cfg.quote_tokens)
    quote = ev.token1 if is_t0 else ev.token0
    info = reader.get_token_info(target)
    q_dec = reader.get_decimals(quote)
    d0, d1 = (info.decimals, q_dec) if is_t0 else (q_dec, info.decimals)
    pp = reader.get_pool_price(ev.pool, d0, d1)
    liquidity = reader.get_pool_liquidity(ev.pool)

    price = pp.price_token1_per_token0
    if price is not None and not is_t0:
        price = 1 / price if price > 0 else None  # express as quote per memecoin

    return {
        "pool": ev.pool,
        "token": target,
        "quote_token": quote,
        "symbol": info.symbol,
        "fee": ev.fee,
        "block": ev.block_number,
        "tx_hash": ev.tx_hash,
        "has_code": info.has_code,
        "total_supply": info.total_supply,
        "decimals": info.decimals,
        "owner": info.owner,
        "owner_renounced": info.owner_renounced,
        "initialized": pp.initialized,
        "price": price,
        "liquidity": liquidity,
        "risk_score": risk_score(info, liquidity, pp.initialized),
    }


@dataclass
class _Pending:
    event: PoolCreated
    polls: int = 0


class Monitor:
    def __init__(self, cfg: Config, reader: ChainReader, decide: DecideFn, executor: Executor, ui):
        self.cfg, self.reader, self.decide, self.executor, self.ui = cfg, reader, decide, executor, ui
        self.next_block: int | None = cfg.start_block
        self._pending: dict[str, _Pending] = {}

    def start(self) -> int:
        head = self.reader.connect()
        if self.next_block is None:
            self.next_block = head
        return head

    def poll_once(self) -> None:
        head = self.reader.latest_block()
        if head >= self.next_block:
            for ev in self.reader.get_pool_created(self.next_block, head):
                self._pending[ev.pool] = _Pending(ev)
                self.ui.add_launch(ev)
            self.next_block = head + 1
        self.ui.head_block = head
        self._process_pending()

    def _process_pending(self) -> None:
        for pool, p in list(self._pending.items()):
            try:
                state = build_state(self.cfg, self.reader, p.event)
            except Exception as exc:  # RPC hiccup etc.: retry next poll, give up eventually
                p.polls += 1
                if p.polls > self.cfg.max_pending_polls:
                    del self._pending[pool]
                    self.ui.log(f"error {pool[:10]}…: {exc}")
                continue
            ready = state["initialized"] and state["liquidity"] > 0
            p.polls += 1
            if not ready and p.polls <= self.cfg.max_pending_polls:
                self.ui.update_launch(state)
                continue
            del self._pending[pool]
            self.ui.update_launch(state)
            self._decide_and_act(state)

    def _decide_and_act(self, state: dict) -> None:
        try:
            raw = self.decide(dict(state))
        except Exception as exc:
            raw = {"action": "skip", "confidence": 0.0, "reason": f"engine error: {exc}"}
        decision = apply_thresholds(validate_decision(raw), state, self.cfg)
        self.ui.add_decision(state, decision)
        if decision["action"] == "buy":
            pos = self.executor.buy(state, decision)
            if pos:
                self.ui.add_position(pos)
                self.ui.log(
                    f"PAPER BUY {pos.symbol or pos.token[:10]} @ {pos.entry_price:.6g} size {pos.size}"
                )
            else:
                self.ui.log(f"buy not executed for {state['pool'][:10]}…")
        else:
            self.ui.log(f"{decision['action'].upper()} {state['symbol'] or state['token'][:10]}")
