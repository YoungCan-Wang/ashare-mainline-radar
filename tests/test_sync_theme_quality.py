"""Fail-closed gates for the weekly theme-basket commit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from ashare_mainline_radar.eastmoney_concepts import THEME_PRESETS, offline_theme_from_preset

ROOT = Path(__file__).resolve().parents[1]


def _load_sync_module():
    path = ROOT / "scripts" / "sync_theme_concepts.py"
    spec = importlib.util.spec_from_file_location("sync_theme_concepts", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNC = _load_sync_module()


def _seeds(name: str) -> list[str]:
    return list(THEME_PRESETS[name]["seed_symbols"])


def _report(**overrides):
    previous = overrides.pop("previous", [{"name": "保险", "symbols": _seeds("保险")}])
    proposed = overrides.pop("proposed", [{"name": "保险", "symbols": _seeds("保险")}])
    kwargs = {
        "previous_themes": previous,
        "proposed_themes": proposed,
        "boards_attempted": 33,
        "boards_failed": 1,
        "presets": 13,
        "seed_fallback_presets": 1,
        "seed_symbols_by_theme": {"保险": _seeds("保险")},
    }
    kwargs.update(overrides)
    return SYNC.evaluate_sync_quality(**kwargs)


def test_healthy_refresh_passes() -> None:
    seeds = _seeds("保险")
    proposed = seeds + ["600000.SH"]
    report = _report(proposed=[{"name": "保险", "symbols": proposed}])
    assert report["ok"]
    assert report["reasons"] == []


def test_board_failure_ratio_above_quarter_skips() -> None:
    report = _report(boards_attempted=33, boards_failed=30, seed_fallback_presets=0)
    assert not report["ok"]
    assert any("board fetch failure ratio" in reason for reason in report["reasons"])


def test_october_source_stamp_run_would_skip() -> None:
    """2026-10-04 had 30/33 board failures and must not commit a source stamp."""
    report = _report(boards_attempted=33, boards_failed=30, seed_fallback_presets=12, presets=13)
    assert not report["ok"]
    assert any("board fetch failure ratio" in reason for reason in report["reasons"])
    assert any("seed-fallback" in reason for reason in report["reasons"])


def test_seed_fallback_ratio_above_fifth_skips() -> None:
    report = _report(seed_fallback_presets=3, presets=13, boards_failed=0)
    assert not report["ok"]
    assert any("seed-fallback" in reason for reason in report["reasons"])


def test_two_seed_fallback_presets_still_pass() -> None:
    report = _report(seed_fallback_presets=2, presets=13, boards_failed=2)
    assert report["ok"]


def test_symbol_count_jump_skips() -> None:
    seeds = _seeds("大消费")
    report = _report(
        previous=[{"name": "大消费", "symbols": seeds}],
        proposed=[{"name": "大消费", "symbols": seeds[:4]}],
        seed_symbols_by_theme={"大消费": seeds},
        boards_failed=0,
        seed_fallback_presets=0,
    )
    assert not report["ok"]
    assert any("abnormal symbol count" in reason for reason in report["reasons"])


def test_small_cap_churn_skips() -> None:
    seeds = _seeds("保险")
    previous = [{"name": "保险", "symbols": seeds}]
    # Replace the basket with seeds plus a crowd of names that are not seeds,
    # large enough to move more than 15% of the previous universe.
    extras = [f"{index:06d}.SZ" for index in range(1, 8)]
    proposed = [{"name": "保险", "symbols": seeds[:4] + extras}]
    report = _report(
        previous=previous,
        proposed=proposed,
        seed_symbols_by_theme={"保险": seeds},
        boards_failed=0,
        seed_fallback_presets=0,
    )
    assert not report["ok"]
    assert any("small-cap churn" in reason or "seed leaders dropped" in reason for reason in report["reasons"])


def test_dropped_seed_leader_skips_even_when_ratios_are_small() -> None:
    seeds = _seeds("电力运营")
    previous = seeds
    proposed = seeds[1:] + ["600000.SH"]
    report = _report(
        previous=[{"name": "电力运营", "symbols": previous}],
        proposed=[{"name": "电力运营", "symbols": proposed}],
        seed_symbols_by_theme={"电力运营": seeds},
        boards_failed=0,
        seed_fallback_presets=0,
    )
    assert not report["ok"]
    assert report["dropped_seed_leaders"] == 1
    assert any("seed leaders dropped" in reason for reason in report["reasons"])


def test_exact_thresholds_still_pass() -> None:
    report = _report(boards_attempted=100, boards_failed=25, presets=10, seed_fallback_presets=2)
    assert report["board_failure_ratio"] == 0.25
    assert report["seed_fallback_ratio"] == 0.20
    assert report["ok"]


def test_enforce_gates_does_not_write_on_skip(tmp_path, monkeypatch) -> None:
    preset = "保险"
    config = {"universe": "CN_Equity_A", "themes": [{"name": preset, "symbols": _seeds(preset), "source": "old"}]}
    path = tmp_path / "theme_baskets.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    def fake_build(name, *, offline, as_of, quality):
        quality["presets"] += 1
        quality["boards_attempted"] += 2
        quality["boards_failed"] += 2
        quality["seed_fallback_presets"] += 1
        return offline_theme_from_preset(name, as_of=as_of)

    monkeypatch.setattr(SYNC, "_build", fake_build)
    code = SYNC.main(
        [
            "--preset",
            preset,
            "--write",
            "--enforce-quality-gates",
            "--config",
            str(path),
            "--as-of",
            "2026-10-05",
        ]
    )
    assert code == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["themes"][0]["source"] == "old"


def test_enforce_gates_writes_when_fetch_is_healthy(tmp_path, monkeypatch) -> None:
    preset = "保险"
    config = {"universe": "CN_Equity_A", "themes": [{"name": preset, "symbols": _seeds(preset), "source": "old"}]}
    path = tmp_path / "theme_baskets.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    def fake_build(name, *, offline, as_of, quality):
        quality["presets"] += 1
        quality["boards_attempted"] += 2
        quality["boards_failed"] += 0
        theme = offline_theme_from_preset(name, as_of=as_of)
        return theme

    monkeypatch.setattr(SYNC, "_build", fake_build)
    code = SYNC.main(
        [
            "--preset",
            preset,
            "--write",
            "--enforce-quality-gates",
            "--config",
            str(path),
            "--as-of",
            "2026-10-05",
        ]
    )
    assert code == 0
    written = json.loads(path.read_text(encoding="utf-8"))
    assert "2026-10-05" in written["themes"][0]["source"]
    assert written["themes"][0]["symbols"] == _seeds(preset)
