import { memo } from "react";

import { formatPercent } from "../lib/format";
import type { PriceLimitBacktestCase, PriceLimitSignal, PriceLimitWatchSummary } from "../types";

interface PriceLimitWatchProps {
  watch?: PriceLimitWatchSummary;
}

function signalTone(signal: PriceLimitSignal): string {
  if (signal.verdict === "禁入") return "red";
  if (signal.verdict === "不买") return "yellow";
  return "green";
}

function caseVerdict(item: PriceLimitBacktestCase): string {
  return item.side === "ceiling" ? "不追" : "不抄";
}

export const PriceLimitWatch = memo(function PriceLimitWatch({ watch }: PriceLimitWatchProps) {
  if (!watch) {
    return <div className="empty-watch">当前日报未包含涨跌停决策数据。</div>;
  }
  const cases = watch.backtest_cases ?? [];
  const signals = watch.signals ?? [];
  return (
    <div className="price-limit-watch">
      <div className="limit-decision-grid" aria-label="涨跌停交易结论">
        <article className="limit-decision-card is-negative">
          <span>天板能不能追</span>
          <strong>{watch.ceiling_verdict ?? "关闭追板通道"}</strong>
          <p>{watch.ceiling_reason ?? "可执行样本外期望为负"}</p>
        </article>
        <article className="limit-decision-card is-negative">
          <span>地板能不能抄</span>
          <strong>{watch.floor_verdict ?? "关闭抄底通道"}</strong>
          <p>{watch.floor_reason ?? "可执行样本外期望为负"}</p>
        </article>
      </div>

      <div className="limit-evidence-heading">
        <div>
          <h3>可执行样本外证据</h3>
          <p>收盘确认后、下一交易日开盘实际可成交才计入，非涨停价/跌停价理想成交。</p>
        </div>
        <span>截至 {watch.evidence_as_of ?? "未标注"}</span>
      </div>
      <div className="table-scroll compact-scroll">
        <table className="data-table limit-evidence-table">
          <thead>
            <tr><th>策略</th><th>样本</th><th>3日胜率</th><th>3日均值</th><th>5日均值</th><th>5%尾部</th><th>结论</th></tr>
          </thead>
          <tbody>
            {cases.map((item) => (
              <tr key={item.name}>
                <td><strong>{item.name}</strong></td>
                <td>{item.test_trades}</td>
                <td>{formatPercent(item.win_rate_3d)}</td>
                <td>{formatPercent(item.avg_return_3d)}</td>
                <td className="metric-negative">{formatPercent(item.avg_return_5d)}</td>
                <td className="metric-negative">{formatPercent(item.p05_return_5d)}</td>
                <td><span className="status-badge red">{caseVerdict(item)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="limit-reopen-gate">
        <strong>通道重开门槛</strong>
        <ul>
          {(watch.reopen_conditions ?? []).map((condition) => <li key={condition}>{condition}</li>)}
        </ul>
      </div>

      <details className="limit-event-details">
        <summary>当日事件 {signals.length} 只 · 涨停触及 {watch.limit_up_touches ?? 0} / 跌停触及 {watch.limit_down_touches ?? 0}</summary>
        {signals.length ? (
          <div className="table-scroll compact-scroll">
            <table className="data-table">
              <thead><tr><th>行为</th><th>标的</th><th>主题</th><th>决策</th><th>处理</th></tr></thead>
              <tbody>
                {signals.map((signal) => (
                  <tr key={`${signal.symbol}:${signal.signal_type}`}>
                    <td>{signal.signal_type}</td>
                    <td><strong>{signal.name}</strong><div className="symbol-code">{signal.symbol}</div></td>
                    <td>{signal.themes?.join("、") || "未映射"}</td>
                    <td><span className={`status-badge ${signalTone(signal)}`}>{signal.verdict ?? "观察"}</span></td>
                    <td>{signal.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty-watch">当日未识别到涨跌停事件。</div>}
      </details>
      <p className="watch-disclaimer">通道重开条件：分钟线影子盘在成交率、期望收益与尾部回撤上重新通过样本外验证。</p>
    </div>
  );
});
