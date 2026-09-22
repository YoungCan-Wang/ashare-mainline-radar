from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ashare_mainline_radar.fib_profit_space import (
    CI_UNIVERSE_LIMIT,
    FETCH_BARS,
    SUCCESS_STATUS,
    UNRUN_STATUS,
    FibProfitSpaceError,
    build_fib_profit_space,
    measure_rows,
    name_is_st,
    persist_fib_profit_space,
    published_board,
    resolve_max_symbols,
    select_symbols,
)
from ashare_mainline_radar.models import KlineSeries

ASOF = date(2026, 9, 18)
SHANGHAI = ZoneInfo("Asia/Shanghai")
LAST_TS = int(datetime(2026, 9, 18, 15, 0, tzinfo=SHANGHAI).timestamp() * 1000)


def _series(symbol: str, lows: list[float], highs: list[float], closes: list[float]) -> KlineSeries:
    count = len(closes)
    return KlineSeries(
        symbol=symbol,
        timestamp=[LAST_TS - (count - 1 - index) * 86_400_000 for index in range(count)],
        open=list(closes),
        high=list(highs),
        low=list(lows),
        close=list(closes),
        volume=[1.0] * count,
        amount=[1.0] * count,
    )


def _paint(
    symbol: str,
    n: int,
    baseline: tuple[float, float, float],
    overrides: dict[int, tuple[float, float, float]],
) -> KlineSeries:
    low, high, close = baseline
    lows = [low] * n
    highs = [high] * n
    closes = [close] * n
    for index, (bar_low, bar_high, bar_close) in overrides.items():
        lows[index] = bar_low
        highs[index] = bar_high
        closes[index] = bar_close
    return _series(symbol, lows, highs, closes)


def _fib_overrides() -> dict[int, tuple[float, float, float]]:
    overrides: dict[int, tuple[float, float, float]] = {
        20: (10.0, 11.0, 10.5),
        70: (19.0, 20.0, 19.6),
        79: (15.5, 16.2, 16.0),
    }
    for index in range(5, 20):
        overrides[index] = (10.5, 18.0, 11.0 + (index - 5) * 0.4)
    return overrides


def _cause_overrides() -> dict[int, tuple[float, float, float]]:
    overrides = {index: (10.6, 11.2, 10.9) for index in range(5, 20)}
    overrides[20] = (10.0, 10.4, 10.2)
    overrides[70] = (21.0, 22.0, 21.5)
    overrides[79] = (17.5, 18.2, 18.0)
    return overrides


def _inverted_overrides() -> dict[int, tuple[float, float, float]]:
    overrides = {index: (10.2, 20.0, 15.0) for index in range(15, 30)}
    overrides[30] = (10.0, 11.0, 10.5)
    overrides[55] = (29.0, 30.0, 29.5)
    for index in range(60, 80):
        overrides[index] = (17.5, 18.0, 17.8)
    return overrides


def test_name_keeps_st_prefix_only() -> None:
    assert name_is_st("*ST测试")
    assert name_is_st("ST测试")
    assert name_is_st(" st测试")
    assert not name_is_st("测试股份")
    assert not name_is_st("长电科技")


def test_space_math_ranks_st_and_drops_invalid_geometry() -> None:
    normal = _paint("600000.SH", 80, (12.0, 13.0, 12.5), _fib_overrides())
    st = _paint("000003.SZ", 80, (12.0, 13.0, 12.5), {**_fib_overrides(), 79: (14.0, 14.6, 14.2)})
    flat = _paint("000001.SZ", 80, (10.0, 10.0, 10.0), {})
    broken = _paint("000002.SZ", 80, (12.0, 13.0, 12.5), {**_fib_overrides(), 79: (11.8, 12.4, 12.0)})
    inverted = _paint("300001.SZ", 80, (16.0, 17.0, 16.5), _inverted_overrides())
    cause = _paint("688001.SH", 80, (12.0, 13.0, 12.5), _cause_overrides())
    rows = measure_rows(
        [
            ("600000.SH", "测试股份", normal),
            ("000003.SZ", "*ST测试", st),
            ("000001.SZ", "平坦股份", flat),
            ("000002.SZ", "破位股份", broken),
            ("300001.SZ", "倒挂股份", inverted),
            ("688001.SH", "原因带", cause),
        ],
        asof=ASOF,
    )
    by_code = {row.code: row for row in rows}

    fib = by_code["600000.SH"]
    assert fib.valid_flag is True
    assert fib.is_st is False
    assert fib.lower_source == "fib_0382"
    assert fib.cause_is_support is False
    assert fib.fib_0382 == pytest.approx(13.82)
    assert fib.fib_or_cause_low == pytest.approx(13.82)
    assert fib.supply_high == pytest.approx(20.0)
    assert fib.supply_low == pytest.approx(19.4)
    assert fib.full_box_pct == pytest.approx((19.4 - 13.82) / 13.82)
    assert fib.remaining_space_pct == pytest.approx((19.4 - 16.0) / 16.0)
    assert fib.swing_amplitude == pytest.approx(1.0)

    st_row = by_code["000003.SZ"]
    assert st_row.is_st is True
    assert st_row.valid_flag is True
    assert st_row.remaining_space_pct == pytest.approx((19.4 - 14.2) / 14.2)
    assert st_row.rank == 1
    assert fib.rank == 2

    assert by_code["000001.SZ"].valid_flag is False
    assert by_code["000001.SZ"].invalid_reason == "swing_too_small"
    assert by_code["000001.SZ"].rank is None
    assert by_code["000002.SZ"].invalid_reason == "broken_support"
    assert by_code["000002.SZ"].rank is None
    assert by_code["300001.SZ"].invalid_reason == "inverted_box"
    assert by_code["300001.SZ"].fib_or_cause_low == pytest.approx(17.64)
    assert by_code["300001.SZ"].rank is None

    cause_row = by_code["688001.SH"]
    assert cause_row.cause_is_support is True
    assert cause_row.lower_source == "cause"
    assert cause_row.fib_0382 == pytest.approx(14.584)
    assert cause_row.fib_or_cause_low == pytest.approx(10.6)
    assert cause_row.supply_low == pytest.approx(21.34)
    assert cause_row.full_box_pct == pytest.approx((21.34 - 10.6) / 10.6)
    assert cause_row.remaining_space_pct == pytest.approx((21.34 - 18.0) / 18.0)
    assert cause_row.valid_flag is True
    assert cause_row.rank == 3

    stored = {row.code for row in rows}
    assert stored == {"600000.SH", "000003.SZ", "000001.SZ", "000002.SZ", "300001.SZ", "688001.SH"}
    assert all("funnel" not in row.as_db() for row in rows)


def test_equal_remaining_space_breaks_ties_by_code() -> None:
    first = _paint("000010.SZ", 80, (12.0, 13.0, 12.5), _fib_overrides())
    second = _paint("000002.SZ", 80, (12.0, 13.0, 12.5), _fib_overrides())
    rows = measure_rows(
        [("000010.SZ", "甲", first), ("000002.SZ", "乙", second)],
        asof=ASOF,
    )
    by_code = {row.code: row for row in rows}
    assert by_code["000002.SZ"].rank == 1
    assert by_code["000010.SZ"].rank == 2
    assert by_code["000002.SZ"].remaining_space_pct == pytest.approx(by_code["000010.SZ"].remaining_space_pct)


def test_batch_matches_single_symbol_geometry() -> None:
    series = _paint("600000.SH", 80, (12.0, 13.0, 12.5), _fib_overrides())
    alone = measure_rows([("600000.SH", "测试股份", series)], asof=ASOF)[0]
    batched = measure_rows(
        [
            ("000001.SZ", "平坦股份", _paint("000001.SZ", 80, (10.0, 10.0, 10.0), {})),
            ("600000.SH", "测试股份", series),
        ],
        asof=ASOF,
    )
    matched = next(row for row in batched if row.code == "600000.SH")
    assert matched.remaining_space_pct == pytest.approx(alone.remaining_space_pct)
    assert matched.full_box_pct == pytest.approx(alone.full_box_pct)
    assert matched.lower_source == alone.lower_source


def test_short_history_is_invalid_geometry() -> None:
    short = _series("000001.SZ", [10.0] * 10, [11.0] * 10, [10.5] * 10)
    row = measure_rows([("000001.SZ", "测试股份", short)], asof=ASOF)[0]
    assert row.valid_flag is False
    assert row.invalid_reason == "missing_bars"
    assert row.rank is None


def test_stale_bar_is_not_ranked() -> None:
    series = _paint("600000.SH", 80, (12.0, 13.0, 12.5), _fib_overrides())
    row = measure_rows([("600000.SH", "测试股份", series)], asof=date(2026, 9, 19))[0]
    assert row.invalid_reason == "stale_bar"
    assert row.valid_flag is False
    assert row.rank is None
    assert row.remaining_space_pct == pytest.approx((19.4 - 16.0) / 16.0)


def test_missing_run_is_unrun_and_hides_rows() -> None:
    leaked = [{"code": "000001.SZ", "rank": 1, "valid_flag": True, "remaining_space_pct": 0.2}]
    assert published_board(None, leaked) == {"state": UNRUN_STATUS, "rows": []}
    assert published_board(UNRUN_STATUS, leaked)["state"] == UNRUN_STATUS
    assert published_board(UNRUN_STATUS, leaked)["rows"] == []
    shown = published_board(
        SUCCESS_STATUS,
        [
            {"code": "000002.SZ", "rank": 2, "valid_flag": True},
            {"code": "000001.SZ", "rank": 1, "valid_flag": True},
            {"code": "000003.SZ", "rank": None, "valid_flag": False},
        ],
    )
    assert shown["state"] == SUCCESS_STATUS
    assert [row["code"] for row in shown["rows"]] == ["000001.SZ", "000002.SZ"]


def test_ci_profile_caps_a_tiny_universe() -> None:
    symbols = [f"{index:06d}.SZ" for index in range(1, 31)]
    assert resolve_max_symbols(0, profile="ci") == CI_UNIVERSE_LIMIT
    assert resolve_max_symbols(100, profile="ci") == CI_UNIVERSE_LIMIT
    assert resolve_max_symbols(3, profile="ci") == 3
    assert resolve_max_symbols(0, profile="production") == 0
    chosen = select_symbols(symbols, requested=0, profile="ci")
    assert len(chosen) == CI_UNIVERSE_LIMIT
    assert chosen != symbols[:CI_UNIVERSE_LIMIT]
    assert select_symbols(symbols, requested=0, profile="production") == symbols


def test_builder_reuses_daily_bars_and_keeps_st() -> None:
    symbols = ["600000.SH", "000003.SZ", "000001.SZ"]
    series = {
        "600000.SH": _paint("600000.SH", 80, (12.0, 13.0, 12.5), _fib_overrides()),
        "000003.SZ": _paint("000003.SZ", 80, (12.0, 13.0, 12.5), {**_fib_overrides(), 79: (14.0, 14.6, 14.2)}),
        "000001.SZ": _paint("000001.SZ", 80, (10.0, 10.0, 10.0), {}),
    }

    class _Client:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] | None = None

        def get_universe(self, universe_id: str) -> dict[str, object]:
            assert universe_id == "CN_Equity_A"
            return {"symbols": symbols}

        def get_instruments(self, requested: list[str]) -> dict[str, dict[str, str]]:
            names = {"600000.SH": "测试股份", "000003.SZ": "*ST测试", "000001.SZ": "平坦股份"}
            return {symbol: {"name": names[symbol]} for symbol in requested}

        def get_klines_batch(self, requested: list[str], period: str, count: int, adjust: str) -> dict[str, KlineSeries]:
            self.kwargs = {"symbols": requested, "period": period, "count": count, "adjust": adjust}
            return {symbol: series[symbol] for symbol in requested}

    client = _Client()
    run = build_fib_profit_space(client=client, max_symbols=0, profile="production")
    assert client.kwargs == {"symbols": symbols, "period": "1d", "count": FETCH_BARS, "adjust": "forward"}
    assert run.asof_date == ASOF
    assert [row.code for row in run.rows] == symbols
    assert run.rows[1].is_st is True
    assert run.rows[1].rank == 1
    assert run.rows[2].valid_flag is False


def test_sparse_bars_do_not_publish_a_success() -> None:
    class _Client:
        def get_universe(self, universe_id: str) -> dict[str, list[str]]:
            return {"symbols": ["600000.SH", "000001.SZ", "000002.SZ"]}

        def get_instruments(self, symbols: list[str]) -> dict[str, dict[str, str]]:
            return {symbol: {"name": "测试"} for symbol in symbols}

        def get_klines_batch(self, symbols: list[str], period: str, count: int, adjust: str) -> dict[str, KlineSeries]:
            return {}

    with pytest.raises(FibProfitSpaceError, match="bar coverage"):
        build_fib_profit_space(client=_Client(), profile="production")


class _Response:
    status = 200

    def read(self) -> bytes:
        return b"null"

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_success_persists_ranked_rows_and_failure_does_not() -> None:
    series = _paint("000003.SZ", 80, (12.0, 13.0, 12.5), {**_fib_overrides(), 79: (14.0, 14.6, 14.2)})
    run_rows = measure_rows([("000003.SZ", "*ST测试", series)], asof=ASOF)

    class _Run:
        asof_date = ASOF
        rows = run_rows

    seen: list[dict[str, object]] = []

    def opener(request, timeout):
        assert timeout == 180
        seen.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    persist_fib_profit_space(
        supabase_url="https://rnqbgmxvqlygymrjmmwv.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="test-key",
        run=_Run(),
        status=SUCCESS_STATUS,
        message="ok",
        asof=ASOF,
        opener=opener,
    )
    assert seen[0]["p_status"] == SUCCESS_STATUS
    assert seen[0]["p_rows"][0]["code"] == "000003.SZ"
    assert seen[0]["p_rows"][0]["is_st"] is True
    assert seen[0]["p_rows"][0]["rank"] == 1
    assert "funnel" not in seen[0]["p_rows"][0]

    persist_fib_profit_space(
        supabase_url="https://rnqbgmxvqlygymrjmmwv.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        radar_ingest_key="test-key",
        run=None,
        status=UNRUN_STATUS,
        message="boom",
        asof=ASOF,
        opener=opener,
    )
    assert seen[1]["p_status"] == UNRUN_STATUS
    assert seen[1]["p_rows"] == []
    with pytest.raises(FibProfitSpaceError, match="empty"):
        persist_fib_profit_space(
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="key",
            radar_ingest_key="key",
            run=None,
            status=SUCCESS_STATUS,
            message="nope",
            asof=ASOF,
            opener=opener,
        )


def test_workflow_is_weekday_bounded_and_isolated() -> None:
    text = Path(".github/workflows/fib-profit-space.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "30 11 * * 1-5" in text
    assert "30 22 * * 0-4" in text
    assert "timeout-minutes: 75" in text
    assert "FIB_PROFIT_SPACE_PROFILE" in text
    assert "tests/test_fib_profit_space.py" in text
    assert "yfyivczvmorpqdyehfmn" not in text
    assert "WyckoffTradingAgent" not in text
    module = Path("ashare_mainline_radar/fib_profit_space.py").read_text(encoding="utf-8")
    assert "yfyivczvmorpqdyehfmn" not in module
    assert "WyckoffTradingAgent" not in module
