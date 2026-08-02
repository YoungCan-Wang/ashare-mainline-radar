import { memo, useState } from "react";

import { clamp, formatNumber, formatPercent, formatRatio } from "../lib/format";
import { gateTone, themeTone } from "../lib/presentation";
import type { RadarRun, ThemeRow } from "../types";

interface ThemeRankingProps {
  run: RadarRun;
  themes: ThemeRow[];
  selectedTheme: string;
  onSelectTheme: (theme: string) => void;
}

const PREVIEW_COUNT = 6;

export const ThemeRanking = memo(function ThemeRanking({ run, themes, selectedTheme, onSelectTheme }: ThemeRankingProps) {
  const [expanded, setExpanded] = useState(false);
  const visibleThemes = expanded ? themes : themes.slice(0, PREVIEW_COUNT);
  const hiddenCount = Math.max(0, themes.length - PREVIEW_COUNT);

  return (
    <section className="section-block themes-block nested-block">
      <div className="section-header">
        <div>
          <h2>主线排名</h2>
          <p>
            已识别 {themes.length} 条主线
            {expanded || hiddenCount === 0 ? " · 点击主线联动筛选下方队列" : ` · 默认 Top${PREVIEW_COUNT}，可展开全部`}
          </p>
        </div>
        <div className="header-actions">
          {selectedTheme !== "all" ? (
            <button className="filter-chip" type="button" onClick={() => onSelectTheme("all")}>
              已筛选：{selectedTheme}
              <span aria-hidden="true"> ×</span>
            </button>
          ) : null}
          <span className={`status-badge ${gateTone(run.gate_level)}`}>
            {run.mode === "universe" ? "全市场扫描" : run.mode === "curated" ? "核心池扫描" : run.mode ?? "扫描模式"}
          </span>
        </div>
      </div>
      <div className="table-scroll compact-scroll">
        <table className="data-table theme-table">
          <thead>
            <tr>
              <th>排名</th>
              <th>主线</th>
              <th>阶段</th>
              <th>强度</th>
              <th>5日广度</th>
              <th>20日广度</th>
              <th>成交</th>
            </tr>
          </thead>
          <tbody>
            {visibleThemes.map((row) => {
              const stage = row.lifecycle_stage ?? row.lifecycle?.stage ?? row.snapshot?.price_phase ?? "阶段待确认";
              const isSelected = selectedTheme === row.theme;
              return (
                <tr
                  key={`${row.run_key}:${row.theme}`}
                  className={`theme-row${isSelected ? " selected" : ""}`}
                  title={isSelected ? "点击取消筛选" : "点击筛选该主线的作战队列"}
                  onClick={() => onSelectTheme(isSelected ? "all" : row.theme)}
                >
                  <td className="rank-cell">{row.rank ?? "--"}</td>
                  <td>
                    <div className="theme-name">{row.theme}</div>
                    <div className="symbol-code">{row.status ?? "--"}</div>
                  </td>
                  <td><span className={`status-badge ${themeTone(stage, row.status)}`}>{stage}</span></td>
                  <td className="score-cell">
                    <div className="score-line">
                      <span className="numeric">{formatNumber(row.score)}</span>
                      <span className="score-track"><span className="score-fill" style={{ width: `${clamp(row.score ?? 0, 0, 100)}%` }} /></span>
                    </div>
                  </td>
                  <td className="numeric">{formatPercent(row.snapshot?.breadth_5d)}</td>
                  <td className="numeric">{formatPercent(row.snapshot?.breadth_20d)}</td>
                  <td className="numeric">{formatRatio(row.snapshot?.amount_heat)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {hiddenCount > 0 ? (
        <div className="expand-footer">
          <button type="button" className="text-button" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "收起，只看 Top6" : `展开其余 ${hiddenCount} 条主线`}
          </button>
        </div>
      ) : null}
    </section>
  );
});
