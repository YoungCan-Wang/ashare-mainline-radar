import { memo, useMemo } from "react";

import { clamp, formatNumber, shortDate } from "../lib/format";
import type { RadarRun, ThemeRow } from "../types";

const CHART_COLORS = ["#147b5d", "#bd4137", "#3468a7", "#a86b12", "#75549a"] as const;
const Y_TICKS = [0, 25, 50, 75, 100] as const;

interface ThemeTrendChartProps {
  runs: RadarRun[];
  allThemes: ThemeRow[];
  selectedThemes: ThemeRow[];
}

export const ThemeTrendChart = memo(function ThemeTrendChart({ runs, allThemes, selectedThemes }: ThemeTrendChartProps) {
  const chart = useMemo(() => {
    const chartRuns = [...runs]
      .sort((a, b) => String(a.market_date).localeCompare(String(b.market_date)))
      .slice(-20);
    const names = selectedThemes.slice(0, 5).map((row) => row.theme);
    const runKeys = new Set(chartRuns.map((run) => run.run_key));
    const historyMap = new Map(
      allThemes
        .filter((row) => runKeys.has(row.run_key) && names.includes(row.theme))
        .map((row) => [`${row.run_key}:${row.theme}`, row.score] as const),
    );
    return { chartRuns, names, historyMap };
  }, [runs, allThemes, selectedThemes]);

  const width = 640;
  const height = 270;
  const margin = { top: 12, right: 14, bottom: 34, left: 38 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const hasHistory = chart.chartRuns.length > 1;

  return (
    <section className="section-block trend-block">
      <div className="section-header">
        <div><h2>主线强度轨迹</h2><p>最近交易日</p></div>
        <div className="chart-legend">
          {chart.names.map((theme, index) => (
            <span className="legend-item" key={theme}>
              <span className="legend-dot" style={{ background: CHART_COLORS[index] }} />{theme}
            </span>
          ))}
        </div>
      </div>
      <div className="chart-wrap">
        {hasHistory ? (
          <svg id="trendChart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="主线强度历史趋势">
            {Y_TICKS.map((value) => {
              const y = margin.top + innerHeight - (value / 100) * innerHeight;
              return (
                <g key={value}>
                  <line x1={margin.left} y1={y} x2={width - margin.right} y2={y} className="chart-grid" />
                  <text x={margin.left - 8} y={y + 3} textAnchor="end" className="chart-axis-label">{value}</text>
                </g>
              );
            })}
            {chart.chartRuns.map((run, index) => {
              const interval = Math.ceil(chart.chartRuns.length / 5);
              if (index !== 0 && index !== chart.chartRuns.length - 1 && index % interval !== 0) return null;
              const x = margin.left + (index / Math.max(1, chart.chartRuns.length - 1)) * innerWidth;
              return <text key={run.run_key} x={x} y={height - 10} textAnchor={index === 0 ? "start" : index === chart.chartRuns.length - 1 ? "end" : "middle"} className="chart-axis-label">{shortDate(run.market_date)}</text>;
            })}
            {chart.names.map((theme, themeIndex) => {
              const points = chart.chartRuns.flatMap((run, index) => {
                const score = chart.historyMap.get(`${run.run_key}:${theme}`);
                if (score == null || !Number.isFinite(score)) return [];
                const x = margin.left + (index / Math.max(1, chart.chartRuns.length - 1)) * innerWidth;
                const y = margin.top + innerHeight - (clamp(score, 0, 100) / 100) * innerHeight;
                return [{ runKey: run.run_key, date: run.market_date, score, x, y }];
              });
              if (points.length < 2) return null;
              return (
                <g key={theme}>
                  <polyline points={points.map((point) => `${point.x},${point.y}`).join(" ")} className="chart-line" stroke={CHART_COLORS[themeIndex]} />
                  {points.map((point) => (
                    <circle key={point.runKey} cx={point.x} cy={point.y} r="3.4" fill={CHART_COLORS[themeIndex]} className="chart-point">
                      <title>{theme} · {point.date} · {formatNumber(point.score)}</title>
                    </circle>
                  ))}
                </g>
              );
            })}
          </svg>
        ) : (
          <div className="empty-state chart-empty visible">历史积累中</div>
        )}
      </div>
    </section>
  );
});
