from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .accumulation import build_accumulation_report
from .config import configured_symbols, theme_keywords, theme_policy_keywords, theme_symbol_map
from .intelligence import collect_intelligence_with_status, intel_match_index
from .market import build_leader_tape, build_theme_snapshots, catalyst_counts, compute_symbol_snapshot
from .market_context import build_market_pulses
from .models import DataSourceStatus, RadarReport, SymbolSnapshot, utc_now_iso
from .next_buy import build_next_buy_report
from .policy import (
    apply_policy_keyword_matches,
    build_policy_signal_report,
    is_policy_item,
    policy_counts_by_theme,
    policy_scores_by_theme,
)
from .strong_stocks import build_strong_stock_report
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
        backtest_hold_days: int = 5,
        strong_stock_limit: int = 12,
        accumulation_limit: int = 12,
    ) -> RadarReport:
        universe_id, symbols = self._symbols_for_mode(mode, max_symbols)
        symbol_to_themes = theme_symbol_map(self.theme_config)
        keywords = theme_keywords(self.theme_config)
        policy_keywords = theme_policy_keywords(self.theme_config)

        instruments = self.client.get_instruments(symbols)
        klines = self.client.get_klines_batch(symbols, period=period, count=lookback_days, adjust=adjust)
        source_statuses = [
            DataSourceStatus(
                name="TickFlow instruments",
                kind="market_data",
                status="ok" if instruments else "empty",
                items=len(instruments),
                message=self.client.source_label,
            ),
            DataSourceStatus(
                name="TickFlow klines",
                kind="market_data",
                status="ok" if klines else "empty",
                items=len(klines),
                message=f"{period}, lookback={lookback_days}, requested={len(symbols)}",
            ),
        ]
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

        intel_items, intel_statuses = collect_intelligence_with_status(self.intel_config, keywords)
        intel_items = apply_policy_keyword_matches(intel_items, policy_keywords)
        source_statuses.extend(intel_statuses)
        non_policy_intel_items = [item for item in intel_items if not is_policy_item(item)]
        catalyst_count_by_theme = catalyst_counts(intel_match_index(non_policy_intel_items))
        themes = build_theme_snapshots(
            self.theme_config,
            snapshots,
            catalyst_count_by_theme,
            policy_counts_by_theme=policy_counts_by_theme(intel_items, policy_keywords),
            policy_scores_by_theme=policy_scores_by_theme(intel_items, policy_keywords),
        )
        policy_signals = build_policy_signal_report(intel_items, themes, policy_keywords)
        leader_tape = build_leader_tape(snapshots, limit=leader_limit)
        market_pulses = build_market_pulses(self.theme_config, snapshots)
        strong_stocks = build_strong_stock_report(
            theme_config=self.theme_config,
            snapshots=snapshots,
            klines=klines,
            themes=themes,
            hold_days=backtest_hold_days,
            max_candidates=strong_stock_limit,
        )
        next_buy = build_next_buy_report(strong_stocks.candidates, themes, market_pulses)
        accumulation = build_accumulation_report(
            snapshots=snapshots,
            klines=klines,
            themes=themes,
            max_candidates=accumulation_limit,
        )

        market_symbols = [str(item["symbol"]) for item in self.theme_config.get("market_watchlist", [])]
        market_watchlist = [snapshots[symbol] for symbol in market_symbols if symbol in snapshots]
        warnings = [
            "本报告只用于研究和交易准备，不构成投资建议。",
            "v0.1 的主题归因主要来自配置文件，未配置题材可能只出现在全市场强势带里。",
        ]
        if self.client.api_key:
            warnings.append("当前使用 TickFlow 完整 API；实时/分钟线能力仍取决于账号权限和本报告配置。")
        else:
            warnings.append("TickFlow 免费模式使用历史日 K，不提供盘中实时更新。")
        return RadarReport(
            generated_at=utc_now_iso(),
            data_as_of=data_as_of,
            mode=mode,
            universe=universe_id,
            scanned_symbols=len(snapshots),
            data_source=self.client.source_label,
            themes=themes,
            market_pulses=market_pulses,
            strong_stocks=strong_stocks,
            next_buy=next_buy,
            accumulation=accumulation,
            policy_signals=policy_signals,
            leader_tape=leader_tape,
            market_watchlist=market_watchlist,
            intel_items=intel_items,
            source_statuses=source_statuses,
            warnings=warnings,
        )


def latest_report_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
