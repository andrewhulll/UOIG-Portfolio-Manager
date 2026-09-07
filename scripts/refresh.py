"""Pull the latest market data into the store.

Usage:
    python -m scripts.refresh            # incremental (nightly)
    python -m scripts.refresh --full     # re-backfill full history
    python -m scripts.refresh --years 3  # custom backfill window
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config  # noqa: E402
from src.ingest.refresh import refresh  # noqa: E402
from src.ingest.benchmark_holdings import api_key as av_key  # noqa: E402
from src.ingest.benchmark_holdings import pull_benchmark_holdings  # noqa: E402
from src.model import cache  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="re-backfill full history")
    ap.add_argument("--years", type=float, help="backfill window in years")
    args = ap.parse_args()

    cfg = load_config()
    s = refresh(cfg, history_years=args.years, full=args.full)
    print(f"Refreshed {s['tickers']} tickers: "
          f"{s['prices']} Capital IQ price rows ({s['status']}, run {s['run_id']})")
    if s["failed"]:
        print(f"  failed ({len(s['failed'])}): {', '.join(s['failed'])}")

    # Benchmark ETF constituents (Alpha Vantage) — powers the optimization
    # page's active-weight metrics. Skipped quietly when no key is configured
    # (set ALPHAVANTAGE_API_KEY or alphavantage.key.txt).
    if av_key():
        try:
            b = pull_benchmark_holdings(cfg)
            print(f"Benchmark holdings: {b['indexes']} indexes, "
                  f"{b['holdings']} constituents, {b['sectors']} sector rows")
            if b["failed"]:
                print(f"  failed: {'; '.join(b['failed'])}")
        except Exception as exc:  # noqa: BLE001 — never fail the price refresh
            print(f"Benchmark holdings pull failed: {exc}")
    else:
        print("Benchmark holdings skipped (no Alpha Vantage key)")

    # Prune expired rows from the durable API cache so the shared table stays small.
    print(f"Cache: purged {cache.purge_expired()} expired rows")

    if s["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
