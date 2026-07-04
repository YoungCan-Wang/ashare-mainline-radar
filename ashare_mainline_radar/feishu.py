from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import RadarReport, pct


class FeishuNotifyError(RuntimeError):
    pass


@dataclass
class FeishuStatus:
    status: str
    code: int | None = None
    message: str | None = None
    response: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    if report.next_buy and report.next_buy.primary:
        plan = report.next_buy.primary
        lines.append("")
        lines.append("下一笔优先候选：")
        lines.append(f"{plan.name} {plan.symbol}｜{plan.theme}｜{plan.decision}｜优先级 {plan.priority_score:.1f}")
        lines.append(f"参与条件：{plan.entry_plan}")
        lines.append(f"失效条件：{plan.invalidation}")
        if report.next_buy.by_theme:
            lines.append("分主线顺势候选：")
            for group in report.next_buy.by_theme[:4]:
                names = "；".join(f"{item.name} {item.symbol}" for item in group.plans[:2])
                lines.append(f"- {group.theme}｜{group.theme_status}｜{names}")
    accumulation_candidates = report.accumulation.candidates if report.accumulation else []
    if accumulation_candidates:
        lines.append("")
        lines.append("低位资金介入候选：")
        for idx, item in enumerate(accumulation_candidates[:5], start=1):
            amount_ratio = "n/a" if item.amount_ratio_5_20 is None else f"{item.amount_ratio_5_20:.2f}x"
            lines.append(
                f"{idx}. {item.name} {item.symbol}｜{item.primary_theme}｜{item.status}｜评分 {item.score:.1f}｜"
                f"60日位置 {pct(item.range_position_60d)}｜成交5/20 {amount_ratio}"
            )
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


def post_feishu_text(webhook_url: str, text: str, timeout: float = 15.0) -> FeishuStatus:
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
        return FeishuStatus(status="failed", message=f"Feishu webhook request failed: {exc}")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return FeishuStatus(status="failed", message=f"Feishu webhook returned non-JSON response: {body[:160]}")
    status_code = parsed.get("StatusCode")
    code = parsed.get("code")
    if status_code not in (None, 0):
        return FeishuStatus(status="failed", code=status_code, message=str(parsed.get("msg") or parsed), response=parsed)
    if code not in (None, 0):
        return FeishuStatus(status="failed", code=code, message=str(parsed.get("msg") or parsed), response=parsed)
    return FeishuStatus(status="sent", code=0, message=str(parsed.get("msg") or "ok"), response=parsed)


def send_feishu_text(webhook_url: str, text: str, timeout: float = 15.0) -> None:
    status = post_feishu_text(webhook_url, text, timeout=timeout)
    if status.status != "sent":
        raise FeishuNotifyError(f"Feishu webhook returned error: {status.to_dict()}") from None


def write_feishu_status(path: str | Path, status: FeishuStatus) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
