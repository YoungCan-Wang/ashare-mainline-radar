from __future__ import annotations

import json
import urllib.error
import urllib.request

from .models import RadarReport, pct


class FeishuNotifyError(RuntimeError):
    pass


def build_feishu_text(report: RadarReport) -> str:
    lines = [
        "A股市场主线雷达",
        f"行情日期：{report.data_as_of or 'n/a'}",
        f"扫描模式：{report.mode}，有效标的：{report.scanned_symbols}",
    ]
    if report.themes:
        lines.append("")
        lines.append("主线 TOP3：")
        for idx, theme in enumerate(report.themes[:3], start=1):
            lines.append(
                f"{idx}. {theme.name}｜{theme.status}｜强度 {theme.score:.1f}｜20日广度 {pct(theme.breadth_20d)}"
            )
    if report.market_pulses:
        pulse = report.market_pulses[0]
        lines.append("")
        lines.append(f"环境：{pulse.name}｜{pulse.status}｜强度 {pulse.score:.1f}")
    candidates = report.strong_stocks.candidates if report.strong_stocks else []
    if candidates:
        lines.append("")
        lines.append(f"强势个股候选（持有{report.strong_stocks.hold_days}日回测）：")
        for idx, item in enumerate(candidates[:6], start=1):
            bt = item.backtest
            win = "n/a" if not bt or bt.win_rate is None else f"{bt.win_rate * 100:.1f}%"
            avg = "n/a" if not bt or bt.avg_return is None else f"{bt.avg_return * 100:.2f}%"
            signals = 0 if not bt else bt.signals
            lines.append(
                f"{idx}. {item.name} {item.symbol}｜{item.theme}｜{item.status}｜评分 {item.score:.1f}｜"
                f"信号 {signals} 次｜胜率 {win}｜均值 {avg}"
            )
    lines.append("")
    lines.append("提示：仅用于研究和交易准备，不构成投资建议。")
    return "\n".join(lines)


def send_feishu_text(webhook_url: str, text: str, timeout: float = 15.0) -> None:
    payload = {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ashare-mainline-radar/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise FeishuNotifyError(f"Feishu webhook request failed: {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FeishuNotifyError(f"Feishu webhook returned non-JSON response: {body[:160]}") from exc
    if parsed.get("StatusCode") not in (None, 0) or parsed.get("code") not in (None, 0):
        raise FeishuNotifyError(f"Feishu webhook returned error: {parsed}") from None
