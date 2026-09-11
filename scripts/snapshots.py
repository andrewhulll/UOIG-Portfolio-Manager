"""Refresh nightly financials, earnings, holders, and research for holdings."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402
from src.ingest.snapshots import refresh_owned_snapshots  # noqa: E402


def main() -> None:
    s = refresh_owned_snapshots(load_config())
    print(f"Owned snapshots: {s['research']}/{s['tickers']} research, "
          f"{s['holders']}/{s['tickers']} holders")
    if s["failed"]:
        print(f"  degraded ({len(s['failed'])}): {', '.join(s['failed'])}")


if __name__ == "__main__":
    main()
