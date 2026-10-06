"""Terminal dashboard (rich): launch feed, decisions, action log, paper positions."""
from __future__ import annotations

import time
from collections import deque

from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .chain import PoolCreated
from .executor import Position

ACTION_STYLE = {"buy": "bold green", "hold": "yellow", "skip": "dim"}


def _ts(t: float | None = None) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t or time.time()))


def _short(addr: str) -> str:
    return f"{addr[:6]}…{addr[-4:]}"


class Dashboard:
    """Holds UI state; the monitor pushes events in, ``render`` draws them."""

    def __init__(self, max_rows: int = 12):
        self.head_block: int | None = None
        self.launches: deque[dict] = deque(maxlen=max_rows)
        self.decisions: deque[dict] = deque(maxlen=max_rows)
        self.actions: deque[str] = deque(maxlen=max_rows * 2)
        self.positions: list[Position] = []
        self.detected = 0

    # -- inputs -------------------------------------------------------------
    def add_launch(self, ev: PoolCreated) -> None:
        self.detected += 1
        self.launches.appendleft({"time": _ts(), "block": ev.block_number, "pool": ev.pool,
                                  "token0": ev.token0, "token1": ev.token1, "fee": ev.fee,
                                  "symbol": None, "price": None, "liquidity": None})

    def update_launch(self, state: dict) -> None:
        for row in self.launches:
            if row["pool"] == state["pool"]:
                row.update(symbol=state["symbol"], price=state["price"], liquidity=state["liquidity"])

    def add_decision(self, state: dict, decision: dict) -> None:
        self.decisions.appendleft({"time": _ts(), "pool": state["pool"], "symbol": state["symbol"],
                                   "token": state["token"], "risk": state["risk_score"], **decision})

    def add_position(self, pos: Position) -> None:
        self.positions.append(pos)

    def log(self, msg: str) -> None:
        self.actions.appendleft(f"[dim]{_ts()}[/dim] {msg}")

    # -- rendering ----------------------------------------------------------
    def _launch_table(self) -> Table:
        t = Table(expand=True, header_style="bold cyan")
        for col in ("Time", "Block", "Pool", "Token", "Fee", "Price", "Liquidity"):
            t.add_column(col)
        for r in self.launches:
            t.add_row(r["time"], str(r["block"]), _short(r["pool"]),
                      r["symbol"] or "?", f"{r['fee'] / 10000:g}%",
                      "-" if r["price"] is None else f"{r['price']:.6g}",
                      "-" if r["liquidity"] is None else str(r["liquidity"]))
        return t

    def _decision_table(self) -> Table:
        t = Table(expand=True, header_style="bold magenta")
        for col in ("Time", "Token", "Action", "Conf", "Risk", "Reason"):
            t.add_column(col, overflow="ellipsis", no_wrap=True)
        for d in self.decisions:
            t.add_row(d["time"], d["symbol"] or _short(d["token"]),
                      Text(d["action"].upper(), style=ACTION_STYLE[d["action"]]),
                      f"{d['confidence']:.2f}", f"{d['risk']:.0f}", d.get("reason", ""))
        return t

    def _positions_table(self) -> Table:
        t = Table(expand=True, header_style="bold green")
        for col in ("Opened", "Token", "Entry", "Size"):
            t.add_column(col)
        for p in self.positions[-6:][::-1]:
            t.add_row(_ts(p.opened_at), p.symbol or _short(p.token), f"{p.entry_price:.6g}", f"{p.size:g}")
        return t

    def render(self) -> Layout:
        header = Text.assemble(
            ("Robinhood Chain memecoin monitor ", "bold"), ("[PAPER TRADING]  ", "bold yellow"),
            f"head block: {self.head_block or '-'}  pools seen: {self.detected}  "
            f"positions: {len(self.positions)}  (Ctrl+C to quit)")
        layout = Layout()
        layout.split_column(
            Layout(Panel(header), size=3),
            Layout(name="top"),
            Layout(name="bottom"),
        )
        layout["top"].split_row(
            Layout(Panel(self._launch_table(), title="New pool launches")),
            Layout(Panel(self._decision_table(), title="Decisions")),
        )
        layout["bottom"].split_row(
            Layout(Panel(Group(*[Text.from_markup(a) for a in self.actions]), title="Action log"), ratio=2),
            Layout(Panel(self._positions_table(), title="Paper positions"), ratio=1),
        )
        return layout
