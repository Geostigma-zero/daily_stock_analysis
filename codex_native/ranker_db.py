"""Read-only adapter for the a_share_ranker shared daily price database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .models import DailyBar
from .tdx import normalize_code


@dataclass(frozen=True)
class RankerDailySnapshot:
    code: str
    name: str
    bars: list[DailyBar]
    db_path: Path


def load_ranker_daily_snapshot(db_path: str | Path, code: str) -> RankerDailySnapshot:
    """Load one A-share's daily bars from a_share_ranker in read-only mode."""
    path = Path(db_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"a_share_ranker daily database not found: {path}")

    normalized = normalize_code(code)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            name = _load_name(conn, normalized) or normalized
            rows = conn.execute(
                """
                SELECT trade_date, code, open, close, high, low, volume, amount, adj_close, source
                FROM daily_prices
                WHERE code = ?
                  AND close IS NOT NULL
                ORDER BY trade_date
                """,
                (normalized,),
            ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"failed to read a_share_ranker daily database {path}: {exc}") from exc

    bars = [_row_to_bar(row) for row in rows]
    if not bars:
        raise RuntimeError(f"no a_share_ranker daily prices found for {normalized}")
    return RankerDailySnapshot(code=normalized, name=name, bars=bars, db_path=path)


def _load_name(conn: sqlite3.Connection, code: str) -> str | None:
    try:
        row = conn.execute("SELECT name FROM stocks WHERE code = ? LIMIT 1", (code,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    name = str(row["name"] or "").strip()
    return name or None


def _row_to_bar(row: sqlite3.Row) -> DailyBar:
    source = str(row["source"] or "unknown")
    adj_close = row["adj_close"]
    return DailyBar(
        trade_date=str(row["trade_date"]),
        code=str(row["code"]).zfill(6),
        open=float(row["open"] or 0),
        close=float(row["close"] or 0),
        high=float(row["high"] or 0),
        low=float(row["low"] or 0),
        volume=float(row["volume"] or 0),
        amount=float(row["amount"] or 0),
        adj_close=float(adj_close) if adj_close is not None else None,
        source=f"ranker-db:{source}",
    )
