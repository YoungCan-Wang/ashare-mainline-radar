import { Moon, Radar, RefreshCw, Sun } from "lucide-react";
import { memo, useState } from "react";

import { formatInteger } from "../lib/format";
import type { RadarRun } from "../types";

type ThemeName = "dark" | "light";

const THEME_STORAGE_KEY = "radar-theme";
const THEME_COLORS: Record<ThemeName, string> = { dark: "#0b0e13", light: "#f4f6f4" };

function readInitialTheme(): ThemeName {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

interface TopBarProps {
  runs: RadarRun[];
  activeRun: RadarRun;
  activeRunKey: string;
  onRunChange: (runKey: string) => void;
}

export const TopBar = memo(function TopBar({ runs, activeRun, activeRunKey, onRunChange }: TopBarProps) {
  const [theme, setTheme] = useState<ThemeName>(readInitialTheme);

  const toggleTheme = () => {
    const next: ThemeName = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // 隐私模式下写不进去就只切当前会话
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[next]);
    setTheme(next);
  };

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
        <button
          className="icon-button"
          type="button"
          title={theme === "dark" ? "切换到日间模式" : "切换到夜间模式"}
          aria-label="切换日夜间主题"
          onClick={toggleTheme}
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </button>
        <button className="icon-button" type="button" title="刷新页面" aria-label="刷新页面" onClick={() => window.location.reload()}>
          <RefreshCw />
        </button>
      </div>
    </header>
  );
});
