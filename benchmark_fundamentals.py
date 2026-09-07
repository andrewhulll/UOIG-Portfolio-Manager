import time
import sqlite3
import datetime as dt
import os
from src.ingest import fundamentals
from src.model import schema

def run_benchmark(num_tickers=10000):
    tickers = [f"TICKER{i}" for i in range(num_tickers)]

    # mock _info
    def mock_info(t):
        return {
            "sector": "Technology",
            "forwardPE": 10,
            "priceToBook": 2,
            "enterpriseToEbitda": 5,
            "marketCap": 1000000,
            "fiftyTwoWeekLow": 10,
            "fiftyTwoWeekHigh": 20,
            "longBusinessSummary": "Test summary"
        }

    fundamentals._info = mock_info

    db_path = "test_benchmark.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    schema.create_schema(conn)

    for t in tickers:
        conn.execute("INSERT INTO securities (ticker, sec_type) VALUES (?, 'stock')", (t,))
    conn.commit()

    start_time = time.time()
    fundamentals.pull_fundamentals({}, conn, tickers)
    end_time = time.time()

    duration = end_time - start_time
    print(f"Time taken to pull {num_tickers} fundamentals: {duration:.4f} seconds")

    conn.close()
    if os.path.exists(db_path):
        os.remove(db_path)

if __name__ == "__main__":
    run_benchmark()
