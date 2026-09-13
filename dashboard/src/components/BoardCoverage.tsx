import { memo } from "react";

import { formatMetricPercent } from "../lib/format";
import type { BoardCoverageSummary, BoardSnapshotRow } from "../types";

interface BoardCoverageProps {
  coverage?: BoardCoverageSummary;
}

function formatAmount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(1)}亿`;
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
}

function kindLabel(kind: string | undefined): string {
  if (kind === "industry") return "行业";
  if (kind === "concept") return "概念";
  return kind ?? "--";
}

function BoardTable({ rows, empty }: { rows: BoardSnapshotRow[]; empty: string }) {
  if (!rows.length) {
    return <div className="empty-watch">{empty}</div>;
  }
  return (
    <div className="table-scroll compact-scroll">
      <table className="data-table board-coverage-table">
        <thead>
          <tr>
            <th>板块原名</th>
            <th>代码</th>
            <th>类型</th>
            <th>涨跌</th>
            <th>成交</th>
            <th>持续</th>
            <th>覆盖</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.source ?? "eastmoney"}:${row.board_code}`}>
              <td>
                <div className="theme-name">{row.board_name}</div>
                <div className="symbol-code">{row.mapped_theme ?? "未覆盖"}</div>
              </td>
              <td className="symbol-code">{row.board_code}</td>
              <td>{kindLabel(row.board_kind)}</td>
              <td className="numeric">{formatMetricPercent(row.change_pct ?? undefined)}</td>
              <td className="numeric">{formatAmount(row.amount)}</td>
              <td className="numeric">{row.persistence_days ?? "--"}</td>
              <td>
                <span className={`status-badge ${row.coverage === "mapped" ? "green" : "yellow"}`}>
                  {row.coverage === "mapped" ? "已入篮" : "未覆盖"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const BoardCoverage = memo(function BoardCoverage({ coverage }: BoardCoverageProps) {
  const missing = coverage?.missing_basket ?? [];
  const mapped = coverage?.mapped_footnote ?? [];
  return (
    <section className="section-block nested-block board-coverage-block">
      <div className="section-header">
        <div>
          <h2>未入篮热板 / 缺篮候选</h2>
          <p>覆盖观察，不是主线成立，也不是买入建议。东财原名原代码；未覆盖 ≠ 最近主题。</p>
        </div>
        <span className="status-badge yellow">
          缺篮 {coverage?.missing_basket_count ?? missing.length} · 热集合 {coverage?.hot_count ?? 0}
        </span>
      </div>
      <BoardTable rows={missing} empty="当前没有未映射且持续满 3 个交易日的缺篮候选。" />
      {mapped.length ? (
        <div className="board-footnote">
          <strong>已在篮子中的当日热板（对照）</strong>
          <ul>
            {mapped.map((row) => (
              <li key={`mapped:${row.board_code}`}>
                {row.board_name} `{row.board_code}` → {row.mapped_theme} · 持续 {row.persistence_days ?? 0} 日
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
});
