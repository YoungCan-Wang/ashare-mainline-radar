from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import configured_symbols, theme_keywords, theme_symbol_map
from .intelligence import collect_intelligence, intel_match_index
from .market import build_leader_tape, build_theme_snapshots, catalyst_counts, compute_symbol_snapshot
from .models import RadarReport, SymbolSnapshot, utc_now_iso
from .tickflow import TickFlowClient


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys([item for item in items if item]))


def _deterministic_cap(symbols: list[str], max_symbols: int, required: list[str]) -> list[str]:
    if max_symbols <= 0 or len(symbols) <= max_symbols:
        return symbols
    required_set = set(required)
    chosen = [symbol for symbol in symbols if symbol in required_set]
    remaining_slots = max(0, max_symbols - len(chosen))
    if remaining_slots == 0:
        return _dedupe(chosen)
    candidates = [symbol for symbol in symbols if symbol not in required_set]
    if len(candidates) <= remaining_slots:
        return _dedupe([*chosen, *candidates])
    step = len(candidates) / remaining_slots
    sampled = [candidates[int(i * step)] for i in range(remaining_slots)]
    return _dedupe([*chosen, *sampled])


class MainlineRadar:
    def __init__(
        self,
        client: TickFlowClient,
        theme_config: dict[str, Any],
        intel_config: dict[str, Any],
    ) -> None:
        self.client = client
        self.theme_config = theme_config
        self.intel_config = intel_config

    def _symbols_for_mode(self, mode: str, max_symbols: int) -> tuple[str, list[str]]:
        universe_id = str(self.theme_config.get("universe") or "CN_Equity_A")
        required = configured_symbols(self.theme_config)
        if mode == "curated":
            return universe_id, required
        if mode != "universe":
            raise ValueError(f"Unsupported mode: {mode}")
        universe = self.client.get_universe(universe_id)
        universe_symbols = [str(symbol) for symbol in universe.get("symbols", [])]
        symbols = _deterministic_cap(universe_symbols, max_symbols=max_symbols, required=required)
        return universe_id, _dedupe([*required, *symbols])

    def run(
        self,
        mode: str = "curated",
        max_symbols: int = 0,
        lookback_days: int = 80,
        period: str = "1d",
        adjust: str = "forward",
        leader_limit: int = 25,
    ) -> RadarReport:
        universe_id, symbols = self._symbols_for_mode(mode, max_symbols)
        symbol_to_themes = theme_symbol_map(self.theme_config)
        keywords = theme_keywords(self.theme_config)

        instruments = self.client.get_instruments(symbols)
        klines = self.client.get_klines_batch(symbols, period=period, count=lookback_days, adjust=adjust)
        last_timestamps = [series.last_timestamp for series in klines.values() if series.last_timestamp is not None]
        data_as_of = None
        if last_timestamps:
            data_as_of = datetime.fromtimestamp(max(last_timestamps) / 1000, timezone.utc).date().isoformat()

        snapshots: dict[str, SymbolSnapshot] = {}
        for symbol, series in klines.items():
            snapshot = compute_symbol_snapshot(
                symbol=symbol,
                series=series,
                instrument=instruments.get(symbol),
                themes=symbol_to_themes.get(symbol, []),
            )
            if snapshot:
                snapshots[symbol] = snapshot

        intel_items = collect_intelligence(self.intel_config, keywords)
        catalyst_count_by_theme = catalyst_counts(intel_match_index(intel_items))
        themes = build_theme_snapshots(self.theme_config, snapshots, catalyst_count_by_theme)
        leader_tape = build_leader_tape(snapshots, limit=leader_limit)

        market_symbols = [str(item["symbol"]) for item in self.theme_config.get("market_watchlist", [])]
        market_watchlist = [snapshots[symbol] for symbol in market_symbols if symbol in snapshots]
        warnings = [
            "本报告只用于研究和交易准备，不构成投资建议。",
            "v0.1 的主题归因主要来自配置文件，未配置题材可能只出现在全市场强势带里。",
            "TickFlow 免费模式使用历史日 K，不提供盘中实时更新。",
        ]
        return RadarReport(
            generated_at=utc_now_iso(),
            data_as_of=data_as_of,
            mode=mode,
            universe=universe_id,
            scanned_symbols=len(snapshots),
            data_source=self.client.source_label,
            themes=themes,
            leader_tape=leader_tape,
            market_watchlist=market_watchlist,
            intel_items=intel_items,
            warnings=warnings,
        )


def latest_report_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
