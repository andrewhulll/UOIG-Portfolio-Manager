"""Repair holdings inflated by the legacy stock-split refresh bug.

The source workbook is a current-position snapshot, so its shares and entry
prices already include historical splits. An older refresh implementation
replayed those splits into the holdings table once more. This guarded repair
only restores rows whose shares changed by a whole-number factor while their
cost basis stayed exactly equal to the workbook baseline.

Dry-run by default::

    python -m scripts.repair_split_inflation
    python -m scripts.repair_split_inflation --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sqlite3

import openpyxl

from src.config import db_path, load_config, workbook_path
from src.io.import_xlsx import parse_fund
from src.model import db, schema


REPAIR_KEY = "repair_split_inflation_v1"


def _baseline_positions(cfg: dict) -> dict[tuple[str, str], dict]:
    # Normal mode preserves the worksheet's calculated bounds. In read-only
    # mode this legacy workbook reports its formatted million-row extent,
    # turning parse_fund's row scan into a multi-minute operation.
    wb = openpyxl.load_workbook(workbook_path(cfg), data_only=True)
    try:
        return {
            (fund["name"], p["ticker"]): p
            for fund in cfg["funds"]
            for p in parse_fund(wb[fund["sheet"]], fund["name"], fund["benchmark"])
            if p["sec_type"] == "stock"
        }
    finally:
        wb.close()


def repair_split_inflation(cfg: dict, conn: sqlite3.Connection, *, apply: bool = False) -> dict:
    schema.create_schema(conn)
    marker = conn.execute(
        db.q(conn, "SELECT value FROM import_meta WHERE key = ?"), (REPAIR_KEY,)
    ).fetchone()
    if marker:
        return {"status": "already-applied", "repaired": []}

    baseline = _baseline_positions(cfg)
    rows = conn.execute("SELECT fund, ticker, shares, entry_price FROM holdings").fetchall()
    repairs = []
    for fund, ticker, shares, entry_price in rows:
        original = baseline.get((fund, ticker))
        if not original or not original["shares"] or not original["entry_price"]:
            continue
        if shares is None or entry_price is None:
            continue

        share_ratio = float(shares) / float(original["shares"])
        whole_ratio = round(share_ratio)
        # The faulty path only created forward-split inflation. Requiring a
        # whole-number share multiplier and invariant cost basis makes this
        # safe around ordinary buys, sells, and entry-price edits.
        if whole_ratio < 2 or not math.isclose(share_ratio, whole_ratio, rel_tol=1e-6):
            continue
        if not math.isclose(
            float(entry_price) * share_ratio,
            float(original["entry_price"]),
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            continue

        repairs.append({
            "fund": fund,
            "ticker": ticker,
            "splitRatio": whole_ratio,
            "sharesBefore": float(shares),
            "sharesAfter": float(original["shares"]),
            "entryPriceBefore": float(entry_price),
            "entryPriceAfter": float(original["entry_price"]),
        })

    if apply:
        for item in repairs:
            conn.execute(
                db.q(conn, "UPDATE holdings SET shares = ?, entry_price = ? WHERE fund = ? AND ticker = ?"),
                (item["sharesAfter"], item["entryPriceAfter"], item["fund"], item["ticker"]),
            )
        marker_value = json.dumps({
            "appliedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "tickers": [item["ticker"] for item in repairs],
        })
        conn.execute(
            db.upsert_sql(conn, "import_meta", ["key", "value"], ["key"]),
            (REPAIR_KEY, marker_value),
        )
        conn.commit()

    return {"status": "applied" if apply else "dry-run", "repaired": repairs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write guarded repairs and the one-time marker")
    args = parser.parse_args()
    cfg = load_config()
    conn = schema.get_connection(db_path(cfg))
    try:
        print(json.dumps(repair_split_inflation(cfg, conn, apply=args.apply), indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
