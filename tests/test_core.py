import json

import pytest

from memecoin_bot.chain import PoolCreated, TokenInfo, parse_pool_created, sqrt_price_to_price, POOL_CREATED_TOPIC
from memecoin_bot.config import Config
from memecoin_bot.dashboard import Dashboard
from memecoin_bot.decision import decide, validate_decision
from memecoin_bot.executor import LiveExecutor, PaperExecutor
from memecoin_bot.monitor import Monitor, pick_target
from memecoin_bot.risk import apply_thresholds, risk_score

T0 = "0x" + "11" * 20
T1 = "0x" + "22" * 20
POOL = "0x" + "33" * 20


def test_sqrt_price_math():
    assert sqrt_price_to_price(2**96, 18, 18) == pytest.approx(1.0)
    assert sqrt_price_to_price(2 * 2**96, 18, 18) == pytest.approx(4.0)
    assert sqrt_price_to_price(2**96, 18, 6) == pytest.approx(1e12)
    assert sqrt_price_to_price(0, 18, 18) is None


def test_parse_pool_created():
    pad = lambda h: "0x" + h.removeprefix("0x").rjust(64, "0")
    log = {
        "topics": [POOL_CREATED_TOPIC, pad(T0), pad(T1), pad(hex(3000))],
        "data": "0x" + (60).to_bytes(32, "big").hex() + POOL.removeprefix("0x").rjust(64, "0"),
        "blockNumber": 7, "transactionHash": "0xabc",
    }
    ev = parse_pool_created(log)
    assert (ev.fee, ev.tick_spacing, ev.block_number) == (3000, 60, 7)
    assert ev.token0.lower() == T0 and ev.token1.lower() == T1 and ev.pool.lower() == POOL


def test_pick_target():
    ev = PoolCreated(1, "0x", T0, T1, 3000, 60, POOL)
    assert pick_target(ev, frozenset()) == (T0, True)
    assert pick_target(ev, frozenset({T0})) == (T1, False)


def test_stub_engine_and_validation():
    assert decide({})["action"] == "skip"
    assert validate_decision({"action": "buy", "confidence": 2})["action"] == "skip"
    assert validate_decision("nope")["action"] == "skip"
    assert validate_decision({"action": "buy", "confidence": 0.9})["action"] == "buy"


def _state(**kw):
    s = {"pool": POOL, "token": T0, "symbol": "MEME", "price": 0.5, "liquidity": 10**7, "risk_score": 10.0}
    return {**s, **kw}


def test_thresholds():
    cfg = Config()
    buy = {"action": "buy", "confidence": 0.9, "reason": ""}
    assert apply_thresholds(buy, _state(), cfg)["action"] == "buy"
    assert apply_thresholds({**buy, "confidence": 0.1}, _state(), cfg)["action"] == "skip"
    assert apply_thresholds(buy, _state(liquidity=1), cfg)["action"] == "skip"
    assert apply_thresholds(buy, _state(risk_score=99), cfg)["action"] == "skip"
    assert apply_thresholds(buy, _state(price=None), cfg)["action"] == "skip"


def test_risk_score():
    ok = TokenInfo(T0, True, 10**24, 18, "M", "0x" + "00" * 20, True)
    assert risk_score(ok, 1, True) == 0
    assert risk_score(TokenInfo(T0, False, None, None, None, None, None), 1, True) == 100
    owned = TokenInfo(T0, True, 10**24, 18, "M", "0x" + "99" * 20, False)
    assert risk_score(owned, 1, True) == 35


def test_paper_executor(tmp_path):
    f = tmp_path / "p.jsonl"
    ex = PaperExecutor(0.1, str(f))
    d = {"action": "buy", "confidence": 0.9}
    pos = ex.buy(_state(), d)
    assert pos and pos.entry_price == 0.5 and pos.opened_at > 0
    assert ex.buy(_state(), d) is None  # no duplicate position
    assert ex.buy(_state(pool="0x" + "44" * 20, price=None), d) is None
    assert json.loads(f.read_text().splitlines()[0])["token"] == T0
    with pytest.raises(NotImplementedError):
        LiveExecutor().buy(_state(), d)


class FakeReader:
    def __init__(self):
        self.liq = 0
        self.events = [PoolCreated(5, "0x1", T0, T1, 3000, 60, POOL)]

    def connect(self): return 5
    def latest_block(self): return 5
    def get_pool_created(self, a, b): return iter(self.events if a <= 5 else [])
    def get_token_info(self, t): return TokenInfo(t, True, 10**24, 18, "MEME", "0x" + "00" * 20, True)
    def get_decimals(self, t): return 18
    def get_pool_price(self, pool, d0, d1):
        from memecoin_bot.chain import PoolPrice
        return PoolPrice(2**96, 0, True, 1.0)
    def get_pool_liquidity(self, pool): return self.liq


def test_monitor_end_to_end(tmp_path):
    cfg = Config(min_liquidity=100, positions_file=str(tmp_path / "p.jsonl"))
    reader, ui = FakeReader(), Dashboard()
    ex = PaperExecutor(0.05)
    mon = Monitor(cfg, reader, lambda s: {"action": "buy", "confidence": 0.95}, ex, ui)
    mon.start()
    mon.poll_once()                    # detected, but no liquidity yet -> pending
    assert ui.detected == 1 and not ui.decisions
    reader.liq = 10**6
    mon.poll_once()                    # liquidity appeared -> decided + paper buy
    assert ui.decisions[0]["action"] == "buy" and len(ex.positions) == 1
    ui.render()                        # must not raise
