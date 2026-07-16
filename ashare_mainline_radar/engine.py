from __future__ import annotations

from pathlib import Path
from typing import Any

from .accumulation import build_accumulation_report
from .config import configured_symbols, theme_keywords, theme_policy_keywords, theme_symbol_map
from .expectations import apply_expectation_overlay, build_expectation_gap_report
from .fundamentals import apply_fundamental_overlay, apply_theme_fundamental_overlay, build_fundamental_report
from .golden_pit import build_golden_pit_report
from .intelligence import collect_intelligence_with_status, intel_match_index
from .market import build_leader_tape, build_theme_snapshots, catalyst_counts, compute_symbol_snapshot
from .market_context import build_market_pulses
from .market_structure import build_market_structure
from .models import DataSourceStatus, RadarReport, SymbolSnapshot, cn_market_date_from_ms, utc_now_iso
from .monthly_base import build_monthly_base_report
from .next_buy import build_next_buy_report
from .policy import (
    apply_policy_keyword_matches,
    build_policy_signal_report,
    is_policy_item,
    policy_counts_by_theme,
    policy_scores_by_theme,
)
from .risk_gate import build_trading_gate
from .strong_stocks import build_strong_stock_report
from .target_prices import build_target_price_report
from .theme_lifecycle import build_theme_lifecycle_report
from .tickflow import TickFlowClient, TickFlowError


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


def _company_symbol(symbol: str, instrument: dict[str, Any] | None) -> bool:
    if not (symbol.endswith(".SH") or symbol.endswith(".SZ")):
        return False
    name = str((instrument or {}).get("name") or "").upper()
    return not any(token in name for token in ("ETF", "LOF", "REIT", "指数", "基金", "转债"))


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
        backtest_hold_days: int = 15,
        strong_stock_limit: int = 12,
        accumulation_limit: int = 12,
    ) -> RadarReport:
        universe_id, symbols = self._symbols_for_mode(mode, max_symbols)
        symbol_to_themes = theme_symbol_map(self.theme_config)
        keywords = theme_keywords(self.theme_config)
        policy_keywords = theme_policy_keywords(self.theme_config)

        instruments = self.client.get_instruments(symbols)
        klines = self.client.get_klines_batch(symbols, period=period, count=lookback_days, adjust=adjust)
        company_symbols = [symbol for symbol in symbols if _company_symbol(symbol, instruments.get(symbol))]
        monthly_klines = {}
        monthly_status = "empty"
        monthly_message = f"1M, lookback=96, requested={len(company_symbols)}"
        try:
            monthly_klines = self.client.get_klines_batch(company_symbols, period="1M", count=96, adjust=adjust)
            monthly_status = "ok" if monthly_klines else "empty"
        except TickFlowError as exc:
            monthly_status = "unavailable"
            monthly_message = str(exc)[:240]
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
            DataSourceStatus(
                name="TickFlow monthly klines",
                kind="market_data",
                status=monthly_status,
                items=len(monthly_klines),
                message=monthly_message,
            ),
        ]
        last_timestamps = [series.last_timestamp for series in klines.values() if series.last_timestamp is not None]
        data_as_of = None
        if last_timestamps:
            data_as_of = cn_market_date_from_ms(max(last_timestamps))

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
        theme_lifecycle = build_theme_lifecycle_report(
            theme_config=self.theme_config,
            klines=klines,
            instruments=instruments,
            current_themes=themes,
        )
        policy_signals = build_policy_signal_report(intel_items, themes, policy_keywords)
        leader_tape = build_leader_tape(snapshots, limit=leader_limit)
        market_pulses = build_market_pulses(self.theme_config, snapshots)
        market_structure = build_market_structure(self.theme_config, klines)
        trading_gate = build_trading_gate(self.theme_config, snapshots, market_pulses, market_structure)
        monthly_bases = build_monthly_base_report(
            monthly_klines=monthly_klines,
            instruments=instruments,
            symbol_to_themes=symbol_to_themes,
            themes=themes,
            gate=trading_gate,
        )
        strong_stocks = build_strong_stock_report(
            theme_config=self.theme_config,
            snapshots=snapshots,
            klines=klines,
            themes=themes,
            hold_days=backtest_hold_days,
            max_candidates=strong_stock_limit * 3,
        )
        accumulation = build_accumulation_report(
            snapshots=snapshots,
            klines=klines,
            themes=themes,
            max_candidates=accumulation_limit * 3,
        )
        preliminary_golden_pits = build_golden_pit_report(
            snapshots=snapshots,
            klines=klines,
            themes=themes,
            gate=trading_gate,
        )
        fundamental_symbols = _dedupe(
            [item.symbol for item in strong_stocks.candidates]
            + [item.symbol for item in accumulation.candidates]
            + [item.symbol for item in preliminary_golden_pits.candidates]
            + [
                symbol
                for symbol in symbol_to_themes
                if symbol in snapshots and _company_symbol(symbol, instruments.get(symbol))
            ]
        )
        raw_metrics: dict[str, list[dict[str, object]]] = {}
        financial_status = "skipped"
        financial_message = "TickFlow完整API密钥未配置"
        if self.client.api_key and fundamental_symbols:
            try:
                raw_metrics = self.client.get_financial_metrics(fundamental_symbols)
                financial_status = "ok" if raw_metrics else "empty"
                financial_message = "候选池核心财务指标"
            except TickFlowError as exc:
                financial_status = "unavailable"
                financial_message = str(exc)[:240]
        fundamentals = build_fundamental_report(
            raw_metrics=raw_metrics,
            prices={symbol: snapshot.last_close for symbol, snapshot in snapshots.items()},
            requested_symbols=fundamental_symbols,
        )
        source_statuses.append(
            DataSourceStatus(
                name="TickFlow financial metrics",
                kind="fundamentals",
                status=financial_status,
                items=fundamentals.covered_symbols,
                message=financial_message,
            )
        )
        apply_fundamental_overlay(
            strong_stocks=strong_stocks,
            accumulation=accumulation,
            fundamentals=fundamentals,
            strong_limit=strong_stock_limit,
            accumulation_limit=accumulation_limit,
        )
        apply_theme_fundamental_overlay(
            themes,
            fundamentals,
            symbol_to_themes,
            {symbol for symbol in symbol_to_themes if _company_symbol(symbol, instruments.get(symbol))},
        )
        expectation_gaps = build_expectation_gap_report(fundamentals, klines, snapshots)
        apply_expectation_overlay(strong_stocks, expectation_gaps)
        golden_pits = build_golden_pit_report(
            snapshots=snapshots,
            klines=klines,
            themes=themes,
            gate=trading_gate,
            fundamentals=fundamentals,
        )
        next_buy = build_next_buy_report(strong_stocks.candidates, themes, market_pulses, trading_gate)
        target_prices = build_target_price_report(
            strong_stocks=strong_stocks,
            accumulation=accumulation,
            klines=klines,
            intel_items=intel_items,
            themes=themes,
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
            market_structure=market_structure,
            trading_gate=trading_gate,
            strong_stocks=strong_stocks,
            next_buy=next_buy,
            accumulation=accumulation,
            golden_pits=golden_pits,
            policy_signals=policy_signals,
            target_prices=target_prices,
            fundamentals=fundamentals,
            expectation_gaps=expectation_gaps,
            leader_tape=leader_tape,
            market_watchlist=market_watchlist,
            intel_items=intel_items,
            source_statuses=source_statuses,
            warnings=warnings,
            monthly_bases=monthly_bases,
            theme_lifecycle=theme_lifecycle,
        )


def latest_report_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
