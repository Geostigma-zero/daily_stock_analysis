"""Local TongDaXin file readers used by the Codex-native CLI."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .models import DailyBar

DAY_RECORD_SIZE = 32
TNF_RECORD_SIZE = 360


@dataclass(frozen=True)
class XrEvent:
    date: str
    cash_per_10: float
    rights_price: float
    bonus_per_10: float
    rights_per_10: float
    share_factor: float | None = None


def normalize_code(code: str) -> str:
    value = str(code).strip().upper()
    if value.startswith(("SH", "SZ", "BJ")):
        value = value[2:]
    for suffix in (".SH", ".SZ", ".BJ", ".SS"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 6:
        raise ValueError(f"A-share code must contain 6 digits: {code!r}")
    return digits


def infer_market(code: str) -> str:
    normalized = normalize_code(code)
    if normalized.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return "sh"
    if normalized.startswith(("000", "001", "002", "003", "200", "300", "301")):
        return "sz"
    if normalized.startswith(("430", "83", "87", "88", "920")):
        return "bj"
    raise ValueError(f"Unsupported A-share market for code: {code!r}")


def find_tdx_day_file(tdx_dir: str | Path, code: str) -> Path:
    root = Path(tdx_dir)
    normalized = normalize_code(code)
    market = infer_market(normalized)
    path = root / "vipdoc" / market / "lday" / f"{market}{normalized}.day"
    if not path.exists():
        raise FileNotFoundError(f"TDX day file not found for {normalized}: {path}")
    return path


def normalize_index_symbol(symbol: str) -> str:
    value = str(symbol).strip().lower()
    if value.endswith((".sh", ".sz")):
        value = f"{value[-2:]}{value[:-3]}"
    if len(value) != 8 or value[:2] not in {"sh", "sz"}:
        raise ValueError(f"index symbol must include sh/sz prefix and 6 digits: {symbol!r}")
    code = value[2:]
    if not code.isdigit():
        raise ValueError(f"index symbol must include sh/sz prefix and 6 digits: {symbol!r}")
    return value


def find_tdx_index_day_file(tdx_dir: str | Path, symbol: str) -> Path:
    root = Path(tdx_dir)
    normalized = normalize_index_symbol(symbol)
    market = normalized[:2]
    code = normalized[2:]
    path = root / "vipdoc" / market / "lday" / f"{market}{code}.day"
    if not path.exists():
        raise FileNotFoundError(f"TDX index day file not found for {normalized}: {path}")
    return path


def parse_tdx_day_file(
    path: str | Path,
    start_date: str | None = None,
    end_date: str | None = None,
    xr_events: list[XrEvent] | None = None,
) -> list[DailyBar]:
    day_path = Path(path)
    code = normalize_code(day_path.stem[-6:])
    start = _normalize_date(start_date) if start_date else None
    end = _normalize_date(end_date) if end_date else None
    rows: list[DailyBar] = []
    data = day_path.read_bytes()
    usable = len(data) - (len(data) % DAY_RECORD_SIZE)

    for offset in range(0, usable, DAY_RECORD_SIZE):
        trade_date, open_i, high_i, low_i, close_i, amount_f, volume_i, _reserved = struct.unpack(
            "<IIIIIfII",
            data[offset : offset + DAY_RECORD_SIZE],
        )
        trade_date_s = str(trade_date)
        if start and trade_date_s < start:
            continue
        if end and trade_date_s > end:
            continue
        close = close_i / 100.0
        rows.append(
            DailyBar(
                trade_date=trade_date_s,
                code=code,
                open=open_i / 100.0,
                close=close,
                high=high_i / 100.0,
                low=low_i / 100.0,
                volume=float(volume_i),
                amount=float(amount_f),
                adj_close=close,
            )
        )

    if xr_events:
        rows = apply_qfq_adjustment(rows, xr_events)
    return rows


def apply_qfq_adjustment(rows: list[DailyBar], events: list[XrEvent]) -> list[DailyBar]:
    if not rows or not events:
        return rows
    ordered_events = sorted(events, key=lambda event: event.date)
    adjustment_end_date = max(row.trade_date for row in rows)
    adjusted_rows: list[DailyBar] = []
    for row in rows:
        adjusted = row.close
        for event in ordered_events:
            if event.date <= row.trade_date or event.date > adjustment_end_date:
                continue
            denominator = event.share_factor or (1 + event.bonus_per_10 / 10.0 + event.rights_per_10 / 10.0)
            if denominator <= 0:
                continue
            adjusted = (adjusted - event.cash_per_10 / 10.0 + event.rights_price * event.rights_per_10 / 10.0) / denominator
        adjusted_rows.append(
            DailyBar(
                trade_date=row.trade_date,
                code=row.code,
                open=row.open,
                close=row.close,
                high=row.high,
                low=row.low,
                volume=row.volume,
                amount=row.amount,
                adj_close=round(adjusted, 6),
                source=row.source,
            )
        )
    return adjusted_rows


def load_tdx_name_map(tdx_dir: str | Path) -> dict[str, str]:
    cache_dir = Path(tdx_dir) / "T0002" / "hq_cache"
    result: dict[str, str] = {}
    for market, filename in (("sh", "shs.tnf"), ("sz", "szs.tnf"), ("bj", "bjs.tnf")):
        path = cache_dir / filename
        if path.exists():
            result.update(parse_tnf_name_file(path, market))
    bj_added = cache_dir / "addedcode_bj.cfg"
    if bj_added.exists():
        result.update(parse_added_bj_names(bj_added))
    return result


def parse_tnf_name_file(path: str | Path, market: str) -> dict[str, str]:
    data = Path(path).read_bytes()
    result: dict[str, str] = {}
    for offset in range(0, len(data) - TNF_RECORD_SIZE + 1, TNF_RECORD_SIZE):
        record = data[offset : offset + TNF_RECORD_SIZE]
        code = record[50:56].split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
        if not code or not code.isdigit() or not _is_a_share_stock_code(market, code):
            continue
        name = record[80:120].lstrip(b"\x00").split(b"\x00", 1)[0].decode("gbk", "ignore").strip()
        if name:
            result[code] = name
    return result


def parse_added_bj_names(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = {}
    text = Path(path).read_text(encoding="gbk", errors="ignore")
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 4:
            continue
        code = parts[2].strip()
        name = parts[3].strip()
        if code.isdigit() and len(code) == 6 and name:
            result[code] = name
    return result


def load_tdx_xr_events(tdx_dir: str | Path) -> dict[str, list[XrEvent]]:
    gbbq_path = Path(tdx_dir) / "T0002" / "hq_cache" / "gbbq"
    if not gbbq_path.exists():
        return {}
    try:
        from pytdx.reader import GbbqReader

        df = GbbqReader().get_df(str(gbbq_path))
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    df["code"] = df["code"].astype(str).str.zfill(6)
    share_factors = _load_share_factors(df)
    events: dict[str, list[XrEvent]] = {}
    for _, row in df[df["category"] == 1].copy().iterrows():
        code = str(row["code"]).zfill(6)
        date = str(int(row["datetime"]))
        event = XrEvent(
            date=date,
            cash_per_10=float(row["hongli_panqianliutong"] or 0),
            rights_price=float(row["peigujia_qianzongguben"] or 0),
            bonus_per_10=float(row["songgu_qianzongguben"] or 0),
            rights_per_10=float(row["peigu_houzongguben"] or 0),
            share_factor=share_factors.get((code, date)),
        )
        if event.cash_per_10 or event.rights_price or event.bonus_per_10 or event.rights_per_10:
            events.setdefault(code, []).append(event)
    return events


def _load_share_factors(df) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for _, row in df[df["category"].isin([5, 9])].iterrows():
        before_total = float(row["peigujia_qianzongguben"] or 0)
        after_total = float(row["peigu_houzongguben"] or 0)
        if before_total <= 0 or after_total <= 0:
            continue
        code = str(row["code"]).zfill(6)
        date = str(int(row["datetime"]))
        factor = after_total / before_total
        current = result.get((code, date))
        if current is None or abs(factor - 1) > abs(current - 1):
            result[(code, date)] = factor
    return result


def _is_a_share_stock_code(market: str, code: str) -> bool:
    if market == "sh":
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if market == "sz":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if market == "bj":
        return code.startswith(("430", "83", "87", "88", "920"))
    return False


def _normalize_date(value: str) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 8:
        raise ValueError(f"date must be YYYYMMDD-compatible: {value!r}")
    return digits
