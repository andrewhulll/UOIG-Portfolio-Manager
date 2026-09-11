"""Repair holdings inflated by the legacy stock-split refresh bug.

The source workbook is a current-position snapshot, so its shares and entry
prices already include historical splits. An older refresh implementation
replayed those splits into the holdings table once more. This guarded repair
only restores rows whose shares changed by an approximate whole-number factor
while their cost basis stayed materially equal to the workbook baseline.

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


REPAIR_KEY = "repair_split_inflation_v2"
RATIO_REL_TOL = 0.005
COST_BASIS_REL_TOL = 0.01


def _position_key(fund: str, ticker: str) -> tuple[str, str]:
    """Normalize legacy DB labels so harmless casing/whitespace cannot hide a row."""
    return str(fund).strip().casefold(), str(ticker).strip().upper()


def _baseline_positions(cfg: dict) -> dict[tuple[str, str], dict]:
    # Normal mode preserves the worksheet's calculated bounds. In read-only
    # mode this legacy workbook reports its formatted million-row extent,
    # turning parse_fund's row scan into a multi-minute operation.
    wb = openpyxl.load_workbook(workbook_path(cfg), data_only=True)
    try:
        return {
            _position_key(fund["name"], p["ticker"]): p
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
    repaired_before: set[tuple[str, str]] = set()
    if marker:
        try:
            saved = json.loads(marker[0])
            repaired_before = {
                _position_key(item["fund"], item["ticker"])
                for item in saved.get("positions", [])
                if isinstance(item, dict) and item.get("fund") and item.get("ticker")
            }
        except (TypeError, ValueError):
            repaired_before = set()

    baseline = _baseline_positions(cfg)
    rows = conn.execute("SELECT fund, ticker, shares, entry_price FROM holdings").fetchall()
    repairs = []
    for fund, ticker, shares, entry_price in rows:
        key = _position_key(fund, ticker)
        if key in repaired_before:
            continue
        original = baseline.get(key)
        if not original or not original["shares"] or not original["entry_price"]:
            continue
        if shares is None or entry_price is None:
            continue

        share_ratio = float(shares) / float(original["shares"])
        whole_ratio = round(share_ratio)
        # The faulty path only created forward-split inflation. Provider and DB
        # values can differ slightly through rounding, so use narrow tolerances
        # around the whole-number share multiplier and invariant total basis.
        # The combination remains selective around ordinary buys and sells.
        if whole_ratio < 2 or not math.isclose(
            share_ratio, whole_ratio, rel_tol=RATIO_REL_TOL
        ):
            continue
        current_basis = float(entry_price) * float(shares)
        original_basis = float(original["entry_price"]) * float(original["shares"])
        if not math.isclose(
            current_basis,
            original_basis,
            rel_tol=COST_BASIS_REL_TOL,
            abs_tol=1.0,
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

    if apply and repairs:
        for item in repairs:
            conn.execute(
                db.q(conn, "UPDATE holdings SET shares = ?, entry_price = ? WHERE fund = ? AND ticker = ?"),
                (item["sharesAfter"], item["entryPriceAfter"], item["fund"], item["ticker"]),
            )
        repaired_positions = repaired_before | {
            _position_key(item["fund"], item["ticker"]) for item in repairs
        }
        marker_value = json.dumps({
            "appliedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "positions": [
                {"fund": fund, "ticker": ticker}
                for fund, ticker in sorted(repaired_positions)
            ],
        })
        conn.execute(
            db.upsert_sql(conn, "import_meta", ["key", "value"], ["key"]),
            (REPAIR_KEY, marker_value),
        )
        conn.commit()

    if not repairs and marker:
        status = "already-applied"
    elif not repairs:
        status = "no-match" if apply else "dry-run"
    else:
        status = "applied" if apply else "dry-run"
    return {"status": status, "repaired": repairs}


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
