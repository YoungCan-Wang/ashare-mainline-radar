import { memo, useMemo } from "react";

import { clamp, formatNumber, shortDate } from "../lib/format";
import type { RadarRun, ThemeRow } from "../types";

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
  const series = useMemo(() => {
    return chart.names.map((theme, themeIndex) => {
      const points = chart.chartRuns.flatMap((run, index) => {
        const score = chart.historyMap.get(`${run.run_key}:${theme}`);
        if (score == null || !Number.isFinite(score)) return [];
        const x = margin.left + (index / Math.max(1, chart.chartRuns.length - 1)) * innerWidth;
        const y = margin.top + innerHeight - (clamp(score, 0, 100) / 100) * innerHeight;
        return [{ runKey: run.run_key, date: run.market_date, score, x, y }];
      });
      return { theme, themeIndex, points };
    });
  }, [chart, innerHeight, innerWidth, margin.left, margin.top]);
  const drawableSeries = series.filter((item) => item.points.length >= 2);
  const hasHistory = chart.chartRuns.length > 1 && drawableSeries.length > 0;
  const emptyHint = chart.chartRuns.length <= 1
    ? "需要至少 2 个交易日的历史强度；当前 data.json 只有 1 天（本地未拉到 Supabase 历史时会出现）"
    : "当前主线在最近交易日里还凑不齐 2 个强度点";

  return (
    <section className="section-block trend-block nested-block">
      <div className="section-header">
        <div>
          <h2>主线强度轨迹</h2>
          <p>{chart.chartRuns.length > 1 ? `最近 ${chart.chartRuns.length} 个交易日` : "最近交易日"}</p>
        </div>
        <div className="chart-legend">
          {chart.names.map((theme, index) => (
            <span className="legend-item" key={theme}>
              <span className="legend-dot" style={{ background: `var(--chart-${index + 1})` }} />{theme}
            </span>
          ))}
        </div>
      </div>
      <div className="chart-wrap">
        {hasHistory ? (
          <svg id="trendChart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="主线强度历史趋势">
            <defs>
              {drawableSeries.map(({ theme, themeIndex }) => (
                <linearGradient key={theme} id={`trend-area-${themeIndex}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" style={{ stopColor: `var(--chart-${themeIndex + 1})`, stopOpacity: 0.2 }} />
                  <stop offset="100%" style={{ stopColor: `var(--chart-${themeIndex + 1})`, stopOpacity: 0 }} />
                </linearGradient>
              ))}
            </defs>
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
            {drawableSeries.map(({ theme, themeIndex, points }) => {
              const baseline = margin.top + innerHeight;
              const linePath = points.map((point) => `${point.x},${point.y}`).join(" ");
              const areaPath = `M ${points[0].x} ${baseline} L ${points.map((point) => `${point.x} ${point.y}`).join(" L ")} L ${points[points.length - 1].x} ${baseline} Z`;
              return (
                <g key={theme} className={`chart-series-${themeIndex}`}>
                  <path d={areaPath} className="chart-area" fill={`url(#trend-area-${themeIndex})`} />
                  <polyline points={linePath} className="chart-line" />
                  {points.map((point) => (
                    <circle key={point.runKey} cx={point.x} cy={point.y} r="3.4" className="chart-point">
                      <title>{theme} · {point.date} · {formatNumber(point.score)}</title>
                    </circle>
                  ))}
                </g>
              );
            })}
          </svg>
        ) : (
          <div className="empty-state chart-empty visible">{emptyHint}</div>
        )}
      </div>
    </section>
  );
});
