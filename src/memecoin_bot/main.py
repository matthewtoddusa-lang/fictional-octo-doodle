"""Entry point: ``python -m memecoin_bot`` (or the ``memecoin-bot`` script)."""
from __future__ import annotations

import argparse
import sys
import time

from rich.console import Console
from rich.live import Live

from .chain import ChainReader
from .config import Config
from .dashboard import Dashboard
from .decision import decide
from .executor import PaperExecutor
from .monitor import Monitor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Robinhood Chain memecoin monitor (paper trading)")
    ap.add_argument("--env-file", default=None, help="path to a .env file (default: ./.env)")
    args = ap.parse_args(argv)

    console = Console()
    try:
        cfg = Config.from_env(args.env_file)
        reader = ChainReader(cfg.rpc_url, cfg.chain_id, cfg.factory_address, cfg.max_block_range)
        ui = Dashboard()
        monitor = Monitor(cfg, reader, decide, PaperExecutor(cfg.position_size, cfg.positions_file), ui)
        head = monitor.start()
    except Exception as exc:
        console.print(f"[red]Startup failed:[/red] {exc}")
        return 1

    ui.log(f"connected to chain {cfg.chain_id}, scanning from block {monitor.next_block} (head {head})")
    try:
        with Live(ui.render(), console=console, screen=True, auto_refresh=False) as live:
            while True:
                try:
                    monitor.poll_once()
                except Exception as exc:  # keep running through transient RPC errors
                    ui.log(f"[red]poll error:[/red] {exc}")
                live.update(ui.render(), refresh=True)
                time.sleep(cfg.poll_interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
