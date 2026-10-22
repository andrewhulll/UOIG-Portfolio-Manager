"""Semantic search over UOIG's historical student-research theses (Supabase pgvector).

`public.thesis_points` holds the Investment Thesis section of every UOIG report,
one row per thesis point, embedded with BAAI/bge-small-en-v1.5 (384-d, cosine).
Queries MUST be embedded with the same model and carry the bge query prefix, or
similarity scores are meaningless. Reads go through the app's existing Postgres
connection (src.model.db), so no extra Supabase key is needed.
"""
from __future__ import annotations

from datetime import date

from src.model.db import connect_pg, database_url, use_postgres

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_embedder = None


def available() -> bool:
    return use_postgres() and bool(database_url())


def _embed_query(text: str) -> list[float]:
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding  # lazy: heavy import, optional dependency
        _embedder = TextEmbedding(MODEL_NAME)
    return next(iter(_embedder.embed([QUERY_PREFIX + text]))).tolist()


def _iso(d) -> str | None:
    return d.isoformat() if isinstance(d, date) else (str(d) if d else None)


def _rows(sql: str, params: tuple, cols: list[str]) -> list[dict]:
    conn = connect_pg()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            out = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()
    for r in out:
        if "report_date" in r:
            r["report_date"] = _iso(r["report_date"])
        if "similarity" in r and r["similarity"] is not None:
            r["similarity"] = round(float(r["similarity"]), 3)
    return out


def search_thesis_points(query: str, k: int = 8, ticker: str | None = None,
                         since: str | None = None, until: str | None = None,
                         latest_only: bool = False) -> list[dict]:
    """Top-k thesis points by cosine similarity. Dates are 'YYYY-MM-DD'."""
    if not available():
        raise RuntimeError("thesis archive needs the Postgres/Supabase connection")
    k = max(1, min(int(k or 8), 20))
    vec = "[" + ",".join(f"{x:.6f}" for x in _embed_query(query)) + "]"
    cols = ["id", "ticker", "company", "report_date", "version_rank", "n_versions",
            "thesis_order", "title", "thesis_text", "source_file", "similarity"]
    return _rows(
        "select " + ", ".join(cols) + " from public.match_thesis_points("
        "%s::vector, %s, %s, %s::date, %s::date, %s)",
        (vec, k, ticker.upper() if ticker else None, since or None, until or None, bool(latest_only)),
        cols,
    )


def ticker_history(ticker: str) -> list[dict]:
    """Every stored thesis point for a ticker, oldest report first."""
    if not available():
        raise RuntimeError("thesis archive needs the Postgres/Supabase connection")
    cols = ["report_date", "version_rank", "thesis_order", "title", "thesis_text", "source_file"]
    return _rows(
        "select " + ", ".join(cols) + " from public.thesis_points where ticker = %s "
        "order by report_date nulls first, thesis_order",
        (ticker.upper().strip(),),
        cols,
    )
