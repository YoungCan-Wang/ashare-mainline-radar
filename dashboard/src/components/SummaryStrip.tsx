import { memo } from "react";

import { formatNumber } from "../lib/format";
import { gateColor, gateLabel } from "../lib/presentation";
import type { RadarRun, SymbolRow, ThemeRow } from "../types";

interface SummaryStripProps {
  run: RadarRun;
  themes: ThemeRow[];
  symbols: SymbolRow[];
}

export const SummaryStrip = memo(function SummaryStrip({ run, themes, symbols }: SummaryStripProps) {
  const topTheme = themes[0];
  const marketStructure = run.summary?.market_structure;
  const nextBuyCount = symbols.filter((row) => row.roles?.includes("next_buy")).length;
  const goldenPitCount = symbols.filter((row) => row.roles?.includes("golden_pit")).length;

  return (
    <section className="summary-strip" aria-label="市场摘要">
      <div className="summary-item summary-primary">
        <span className="summary-label">第一主线</span>
        <strong className="summary-value">{topTheme?.theme ?? run.top_theme ?? "暂无主线"}</strong>
        <span className="summary-meta">
          {topTheme ? `${topTheme.status ?? "状态待确认"} · 强度 ${formatNumber(topTheme.score)}` : "等待数据"}
        </span>
      </div>
      <div className="summary-item">
        <span className="summary-label">市场闸门</span>
        <strong className="summary-value" style={{ color: gateColor(run.gate_level) }}>
          {run.gate_state ?? "未覆盖"}
        </strong>
        <span className="summary-meta">
          {gateLabel(run.gate_level)} · {formatNumber(run.gate_score)}分
        </span>
      </div>
      <div className="summary-item">
        <span className="summary-label">指数结构</span>
        <strong className="summary-value">{marketStructure?.status ?? "未覆盖"}</strong>
        <span className="summary-meta">
          {marketStructure?.score == null ? "结构分未覆盖" : `确认分 ${formatNumber(marketStructure.score)}`}
        </span>
      </div>
      <div className="summary-item">
        <span className="summary-label">作战标的</span>
        <strong className="summary-value">{symbols.length} 只</strong>
        <span className="summary-meta">建仓 {nextBuyCount} · 黄金坑 {goldenPitCount}</span>
      </div>
    </section>
  );
});
