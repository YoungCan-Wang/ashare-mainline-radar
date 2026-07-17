import { Radar, RefreshCw } from "lucide-react";
import { memo } from "react";

import { formatInteger } from "../lib/format";
import type { RadarRun } from "../types";

interface TopBarProps {
  runs: RadarRun[];
  activeRun: RadarRun;
  activeRunKey: string;
  onRunChange: (runKey: string) => void;
}

export const TopBar = memo(function TopBar({ runs, activeRun, activeRunKey, onRunChange }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">
          <Radar />
        </div>
        <div>
          <div className="brand-title">A股主线作战台</div>
          <div className="brand-subtitle">
            行情 {activeRun.market_date ?? "--"} · 扫描 {formatInteger(activeRun.scanned_symbols)} 只
          </div>
        </div>
      </div>
      <div className="topbar-actions">
        <label className="field-label" htmlFor="run-select">
          行情日期
        </label>
        <select
          id="run-select"
          className="select-control"
          value={activeRunKey}
          onChange={(event) => onRunChange(event.target.value)}
        >
          {runs.map((run) => (
            <option key={run.run_key} value={run.run_key}>
              {run.market_date ?? "日期未知"}
            </option>
          ))}
        </select>
        <button className="icon-button" type="button" title="刷新页面" aria-label="刷新页面" onClick={() => window.location.reload()}>
          <RefreshCw />
        </button>
      </div>
    </header>
  );
});
