from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .supabase_rest import fetch_rows, upsert_rows
from .tickflow import TickFlowClient

ACTIONABLE_ROLES = frozenset(
    {"next_buy", "strong_stock", "golden_pit", "accumulation", "monthly_base", "expectation_gap"}
)
CHINA_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class QuoteRefreshStatus:
    status: str
    run_key: str | None
    requested_symbols: int
    refreshed_symbols: int
    missing_symbols: int
    quote_date: str | None
    message: str

    @property
    def should_deploy(self) -> bool:
        return self.status == "refreshed" and self.refreshed_symbols > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _roles(row: dict[str, Any]) -> set[str]:
    value = row.get("roles")
    return {str(role) for role in value} if isinstance(value, list) else set()


def refresh_selected_quotes(
    *,
    client: TickFlowClient | None = None,
    supabase_url: str | None = None,
    supabase_publishable_key: str | None = None,
    radar_ingest_key: str | None = None,
    now: datetime | None = None,
    require_current_market_date: bool = True,
    opener: Callable[..., Any] = urlopen,
) -> QuoteRefreshStatus:
    url = supabase_url or os.getenv("SUPABASE_URL")
    api_key = supabase_publishable_key or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    ingest_key = radar_ingest_key or os.getenv("RADAR_INGEST_KEY")
    if not url or not api_key or not ingest_key:
        raise RuntimeError("SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and RADAR_INGEST_KEY are required")

    runs = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_runs",
        order="market_date.desc,generated_at.desc",
        max_rows=1,
        opener=opener,
    )
    if not runs:
        return QuoteRefreshStatus("skipped", None, 0, 0, 0, None, "no radar run is stored")

    run_key = str(runs[0].get("run_key") or "")
    snapshots = fetch_rows(
        url,
        api_key,
        ingest_key,
        "radar_symbol_snapshots",
        order="priority_score.desc.nullslast,symbol.asc",
        max_rows=5000,
        filters={"run_key": f"eq.{run_key}"},
        opener=opener,
    )
    symbols = sorted(
        {
            str(row["symbol"])
            for row in snapshots
            if row.get("symbol") and _roles(row).intersection(ACTIONABLE_ROLES)
        }
    )
    if not symbols:
        return QuoteRefreshStatus("skipped", run_key, 0, 0, 0, None, "current run has no actionable symbols")

    provider = client or TickFlowClient()
    quotes = provider.get_quotes(symbols)
    current_time = now or datetime.now(timezone.utc)
    current_market_date = current_time.astimezone(CHINA_TZ).date()
    rows: list[dict[str, Any]] = []
    quote_dates = set()
    for symbol in symbols:
        quote = quotes.get(symbol)
        if quote is None:
            continue
        quote_at = datetime.fromtimestamp(quote.timestamp / 1000, tz=timezone.utc)
        quote_date = quote_at.astimezone(CHINA_TZ).date()
        if require_current_market_date and quote_date != current_market_date:
            continue
        change_pct = quote.change_pct
        if change_pct is None and quote.prev_close and quote.prev_close > 0:
            change_pct = quote.last_price / quote.prev_close - 1
        quote_dates.add(quote_date.isoformat())
        rows.append(
            {
                "symbol": symbol,
                "quote_at": quote_at.isoformat(),
                "quote_date": quote_date.isoformat(),
                "latest_price": quote.last_price,
                "prev_close": quote.prev_close,
                "daily_change_pct": change_pct,
                "session": quote.session,
                "source": "tickflow_quotes",
                "refreshed_at": current_time.astimezone(timezone.utc).isoformat(),
            }
        )

    if not rows:
        return QuoteRefreshStatus(
            "skipped",
            run_key,
            len(symbols),
            0,
            len(symbols),
            None,
            "TickFlow returned no quote stamped with the current China market date",
        )

    upsert_rows(url, api_key, ingest_key, "radar_symbol_quotes", "symbol", rows, opener)
    return QuoteRefreshStatus(
        "refreshed",
        run_key,
        len(symbols),
        len(rows),
        len(symbols) - len(rows),
        max(quote_dates),
        "current actionable pool quotes refreshed",
    )
