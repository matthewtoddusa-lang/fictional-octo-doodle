"""Read-only access to Robinhood Chain: pool creation events, ERC-20 and pool state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from web3 import Web3
from web3.exceptions import ContractLogicError

try:  # web3 v7 / v8 expose this name; older helpers may differ
    from web3.exceptions import BadFunctionCallOutput
except ImportError:  # pragma: no cover
    BadFunctionCallOutput = ContractLogicError  # type: ignore[misc,assignment]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DEAD_ADDRESS = "0x000000000000000000000000000000000000dead"
Q96 = 2**96

POOL_CREATED_TOPIC = (
    "0x" + Web3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex().removeprefix("0x")
)

ERC20_ABI = [
    {"name": "totalSupply", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint256"}]},
    {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
    {"name": "symbol", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
    {"name": "owner", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
]

POOL_ABI = [
    {
        "name": "slot0", "type": "function", "stateMutability": "view", "inputs": [],
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"}, {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"}, {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"}, {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"},
        ],
    },
    {"name": "liquidity", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint128"}]},
]


@dataclass(frozen=True)
class PoolCreated:
    block_number: int
    tx_hash: str
    token0: str
    token1: str
    fee: int
    tick_spacing: int
    pool: str


@dataclass(frozen=True)
class TokenInfo:
    address: str
    has_code: bool
    total_supply: int | None
    decimals: int | None
    symbol: str | None
    owner: str | None  # None => token has no readable owner() function
    owner_renounced: bool | None  # None => unknown (no owner() function)


@dataclass(frozen=True)
class PoolPrice:
    sqrt_price_x96: int
    tick: int
    initialized: bool
    price_token1_per_token0: float | None  # decimal-adjusted; None if uninitialized/unknown


def sqrt_price_to_price(sqrt_price_x96: int, decimals0: int, decimals1: int) -> float | None:
    """Convert Uniswap V3 sqrtPriceX96 to a decimal-adjusted price of token0 in token1."""
    if sqrt_price_x96 <= 0:
        return None
    ratio = (sqrt_price_x96 / Q96) ** 2
    return ratio * 10 ** (decimals0 - decimals1)


def _addr_from_topic(topic: bytes | str) -> str:
    raw = topic.hex() if isinstance(topic, (bytes, bytearray)) else topic
    return Web3.to_checksum_address("0x" + raw.removeprefix("0x")[-40:])


def _topic_int(topic: bytes | str) -> int:
    raw = topic.hex() if isinstance(topic, (bytes, bytearray)) else topic
    return int(raw.removeprefix("0x"), 16)


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= 1 << (bits - 1) else value


def parse_pool_created(log) -> PoolCreated:
    """Decode a raw PoolCreated log (token0/token1/fee are indexed topics)."""
    topics = log["topics"]
    data = log["data"]
    data_hex = (data.hex() if isinstance(data, (bytes, bytearray)) else data).removeprefix("0x")
    tick_spacing = _signed(int(data_hex[0:64], 16), 24)
    pool = Web3.to_checksum_address("0x" + data_hex[64:128][-40:])
    tx = log["transactionHash"]
    return PoolCreated(
        block_number=log["blockNumber"],
        tx_hash=tx.hex() if isinstance(tx, (bytes, bytearray)) else tx,
        token0=_addr_from_topic(topics[1]),
        token1=_addr_from_topic(topics[2]),
        fee=_topic_int(topics[3]),
        tick_spacing=tick_spacing,
        pool=pool,
    )


class ChainReader:
    def __init__(self, rpc_url: str, chain_id: int, factory_address: str, max_block_range: int = 2000):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        self.expected_chain_id = chain_id
        self.factory = Web3.to_checksum_address(factory_address)
        self.max_block_range = max_block_range
        self._decimals_cache: dict[str, int] = {}

    # -- connection ---------------------------------------------------------
    def connect(self) -> int:
        """Verify the endpoint is reachable and on the right chain; return the head block."""
        actual = self.w3.eth.chain_id
        if actual != self.expected_chain_id:
            raise RuntimeError(f"RPC reports chain ID {actual}, expected {self.expected_chain_id}")
        return self.w3.eth.block_number

    def latest_block(self) -> int:
        return self.w3.eth.block_number

    # -- factory events -----------------------------------------------------
    def get_pool_created(self, from_block: int, to_block: int) -> Iterator[PoolCreated]:
        """Yield PoolCreated events in [from_block, to_block], chunked to the RPC's range limit."""
        start = from_block
        while start <= to_block:
            end = min(start + self.max_block_range - 1, to_block)
            logs = self.w3.eth.get_logs(
                {"address": self.factory, "fromBlock": start, "toBlock": end, "topics": [POOL_CREATED_TOPIC]}
            )
            for log in sorted(logs, key=lambda l: (l["blockNumber"], l["logIndex"])):
                yield parse_pool_created(log)
            start = end + 1

    # -- ERC-20 -------------------------------------------------------------
    def _call(self, fn, default=None):
        try:
            return fn.call()
        except (ContractLogicError, BadFunctionCallOutput, ValueError):
            return default

    def get_token_info(self, token: str) -> TokenInfo:
        """Total supply, owner status and bytecode presence for an ERC-20 address."""
        addr = Web3.to_checksum_address(token)
        has_code = len(self.w3.eth.get_code(addr)) > 0
        if not has_code:
            return TokenInfo(addr, False, None, None, None, None, None)
        c = self.w3.eth.contract(address=addr, abi=ERC20_ABI)
        decimals = self._call(c.functions.decimals())
        if decimals is not None:
            self._decimals_cache[addr] = decimals
        owner = self._call(c.functions.owner())
        renounced = None if owner is None else owner.lower() in (ZERO_ADDRESS, DEAD_ADDRESS)
        return TokenInfo(
            address=addr,
            has_code=True,
            total_supply=self._call(c.functions.totalSupply()),
            decimals=decimals,
            symbol=self._call(c.functions.symbol()),
            owner=owner,
            owner_renounced=renounced,
        )

    def get_decimals(self, token: str) -> int | None:
        addr = Web3.to_checksum_address(token)
        if addr not in self._decimals_cache:
            d = self._call(self.w3.eth.contract(address=addr, abi=ERC20_ABI).functions.decimals())
            if d is None:
                return None
            self._decimals_cache[addr] = d
        return self._decimals_cache[addr]

    # -- pool ---------------------------------------------------------------
    def get_pool_price(self, pool: str, decimals0: int | None, decimals1: int | None) -> PoolPrice:
        """Read slot0. Price is token1-per-token0, decimal-adjusted when both decimals are known."""
        c = self.w3.eth.contract(address=Web3.to_checksum_address(pool), abi=POOL_ABI)
        sqrt_price, tick, *_ = c.functions.slot0().call()
        price = None
        if decimals0 is not None and decimals1 is not None:
            price = sqrt_price_to_price(sqrt_price, decimals0, decimals1)
        return PoolPrice(sqrt_price, tick, sqrt_price > 0, price)

    def get_pool_liquidity(self, pool: str) -> int:
        c = self.w3.eth.contract(address=Web3.to_checksum_address(pool), abi=POOL_ABI)
        return c.functions.liquidity().call()
