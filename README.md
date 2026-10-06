# Robinhood Chain Memecoin Monitor

A read-only monitoring bot for Robinhood Chain (chain ID 4663). It watches the Uniswap V3
factory for new pools, gathers on-chain state, asks a pluggable decision engine what to do,
and **paper-trades** the result in a `rich` terminal dashboard. **No real transactions are sent.**

## Layout

```
src/memecoin_bot/
  chain.py      ChainReader: PoolCreated events, ERC-20 info, pool slot0 price/liquidity
  decision.py   decide(state) -> {"action", "confidence"}  (STUB: always "skip")
  risk.py       heuristic risk score + threshold gating
  executor.py   Executor interface, PaperExecutor, LiveExecutor (swap stubbed)
  monitor.py    polling loop: detect -> build state -> decide -> gate -> execute
  dashboard.py  rich terminal UI
  config.py     .env loading
tests/          unit tests (offline, fake reader)
```

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .                 # or: export PYTHONPATH=src
cp .env.example .env             # edit thresholds / RPC as needed
python -m memecoin_bot           # Ctrl+C to quit
pytest                           # run tests
```

## Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `RPC_URL` | Robinhood Chain mainnet | JSON-RPC endpoint |
| `CHAIN_ID` | `4663` | Verified on startup; the bot refuses to run on a mismatch |
| `UNISWAP_V3_FACTORY` | `0x1f7d…2EfA` | Factory watched for `PoolCreated` |
| `QUOTE_TOKENS` | empty | Comma-separated quote tokens (WETH, stables). The *other* token in a pool is treated as the memecoin; if empty, token0 is assumed |
| `POLL_INTERVAL_SECONDS` | `5` | Poll period |
| `START_BLOCK` | head | First block to scan (set lower to replay history) |
| `MAX_BLOCK_RANGE` | `2000` | `eth_getLogs` span per request |
| `MAX_PENDING_POLLS` | `20` | New pools with no liquidity are re-checked this many polls before being skipped |
| `MIN_LIQUIDITY` | `1000000` | Min raw V3 `liquidity()` for a buy |
| `MIN_CONFIDENCE` | `0.7` | Min engine confidence for a buy |
| `MAX_RISK_SCORE` | `60` | Max heuristic risk score (0-100) for a buy |
| `PAPER_POSITION_SIZE` | `0.05` | Simulated size per position (quote-token units) |
| `POSITIONS_FILE` | `data/positions.jsonl` | Paper positions are appended here |

## Plugging in your model

Edit `decide()` in `src/memecoin_bot/decision.py` (or pass your own function to `Monitor` in
`main.py`). It receives a JSON-serialisable `state` dict:

`pool, token, quote_token, symbol, fee, block, tx_hash, has_code, total_supply, decimals,
owner, owner_renounced, initialized, price, liquidity, risk_score`

and must return `{"action": "buy"|"hold"|"skip", "confidence": 0..1}` (optional `"reason"`
is shown on the dashboard). Malformed output becomes a safe `skip`. Your `.env` thresholds
are enforced **after** the engine, so a "buy" below `MIN_CONFIDENCE`/`MIN_LIQUIDITY` or above
`MAX_RISK_SCORE` is downgraded to `skip`.

## Notes and limits

- `price` is quote-per-memecoin, decimal-adjusted, from `slot0.sqrtPriceX96`. It is `None` until the pool is initialised.
- `owner_renounced` is `None` when the token has no `owner()` function (not necessarily safe).
- The risk score is a simple placeholder heuristic, not a rug-pull detector.
- Live trading: `LiveExecutor._swap` raises `NotImplementedError` by design.
- Not financial advice; memecoins are extremely risky.
