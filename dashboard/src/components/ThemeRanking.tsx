import { memo } from "react";

import { clamp, formatNumber, formatPercent, formatRatio } from "../lib/format";
import { gateTone, themeTone } from "../lib/presentation";
import type { RadarRun, ThemeRow } from "../types";

interface ThemeRankingProps {
  run: RadarRun;
  themes: ThemeRow[];
}

export const ThemeRanking = memo(function ThemeRanking({ run, themes }: ThemeRankingProps) {
  return (
    <section className="section-block themes-block">
      <div className="section-header">
        <div>
          <h2>主线排名</h2>
          <p>已识别 {themes.length} 条主线</p>
        </div>
        <span className={`status-badge ${gateTone(run.gate_level)}`}>
          {run.mode === "universe" ? "全市场扫描" : run.mode === "curated" ? "核心池扫描" : run.mode ?? "扫描模式"}
        </span>
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
            {themes.map((row) => {
              const stage = row.lifecycle_stage ?? row.lifecycle?.stage ?? row.snapshot?.price_phase ?? "阶段待确认";
              return (
                <tr key={`${row.run_key}:${row.theme}`}>
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
    </section>
  );
});
