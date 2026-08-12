import { memo } from "react";

import type { PriceLimitSignal, PriceLimitWatchSummary } from "../types";

interface PriceLimitWatchProps {
  watch?: PriceLimitWatchSummary;
}

function signalTone(signal: PriceLimitSignal): string {
  if (["天地板", "收盘封跌停", "一字跌停"].includes(signal.signal_type)) return "red";
  if (["炸板", "跌停打开", "地天板"].includes(signal.signal_type)) return "yellow";
  return "green";
}

export const PriceLimitWatch = memo(function PriceLimitWatch({ watch }: PriceLimitWatchProps) {
  if (!watch) {
    return <div className="empty-watch">当前日报未包含涨跌停观察数据。</div>;
  }
  const signals = watch.signals ?? [];
  return (
    <div className="price-limit-watch">
      <div className="price-limit-stats">
        <div><span>涨停触及</span><strong>{watch.limit_up_touches ?? 0}</strong></div>
        <div><span>收盘封板</span><strong>{watch.closed_limit_up ?? 0}</strong></div>
        <div><span>首板封住</span><strong>{watch.first_board_closed ?? 0}</strong></div>
        <div><span>一字涨停/炸板</span><strong>{watch.one_price_limit_up ?? 0}/{watch.broken_boards ?? 0}</strong></div>
        <div><span>跌停触及</span><strong>{watch.limit_down_touches ?? 0}</strong></div>
        <div><span>封跌停/一字</span><strong>{watch.closed_limit_down ?? 0}/{watch.one_price_limit_down ?? 0}</strong></div>
        <div><span>跌停打开</span><strong>{watch.broken_floors ?? 0}</strong></div>
        <div><span>天地/地天</span><strong>{(watch.ceiling_to_floor ?? 0) + (watch.floor_to_ceiling ?? 0)}</strong></div>
      </div>
      {signals.length ? (
        <div className="table-scroll compact-scroll">
          <table className="data-table">
            <thead><tr><th>行为</th><th>标的</th><th>主题</th><th>解释</th></tr></thead>
            <tbody>
              {signals.map((signal) => (
                <tr key={`${signal.symbol}:${signal.signal_type}`}>
                  <td><span className={`status-badge ${signalTone(signal)}`}>{signal.signal_type}</span></td>
                  <td><strong>{signal.name}</strong><div className="symbol-code">{signal.symbol}</div></td>
                  <td>{signal.themes?.join("、") || "未映射"}</td>
                  <td>{signal.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <div className="empty-watch">当日未识别到涨跌停行为。</div>}
      <p className="watch-disclaimer">收盘后后验观察，不自动生成交易计划；真实成交仍需分钟线和盘口验证。</p>
    </div>
  );
});
