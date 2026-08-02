import { AlertCircle, Radar } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { CandidateDrawer } from "./components/CandidateDrawer";
import { CandidateQueue } from "./components/CandidateQueue";
import { CollapsibleSection } from "./components/CollapsibleSection";
import { SummaryStrip } from "./components/SummaryStrip";
import { ThemeRanking } from "./components/ThemeRanking";
import { ThemeTrendChart } from "./components/ThemeTrendChart";
import { TopBar } from "./components/TopBar";
import { useDashboardData } from "./hooks/useDashboardData";
import { formatDateTime } from "./lib/format";
import type { SymbolRow } from "./types";

export function DashboardApp() {
  const query = useDashboardData();
  const [selectedRunKey, setSelectedRunKey] = useState<string | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<SymbolRow | null>(null);
  const [themeFilter, setThemeFilter] = useState("all");
  const [insightOpen, setInsightOpen] = useState(true);

  const data = query.data;
  const activeRunKey = selectedRunKey ?? data?.current_run_key ?? data?.runs[0]?.run_key;
  const activeRun = data?.runs.find((run) => run.run_key === activeRunKey) ?? data?.runs[0];
  const activeThemes = useMemo(
    () => data?.themes.filter((row) => row.run_key === activeRunKey).sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999)) ?? [],
    [data?.themes, activeRunKey],
  );
  const activeSymbols = useMemo(
    () => data?.symbols.filter((row) => row.run_key === activeRunKey) ?? [],
    [data?.symbols, activeRunKey],
  );
  const handleRunChange = useCallback((runKey: string) => {
    setSelectedRunKey(runKey);
    setSelectedCandidate(null);
    setThemeFilter("all");
  }, []);
  const handleDrawerClose = useCallback(() => setSelectedCandidate(null), []);
  const insightSubtitle = themeFilter === "all"
    ? `${activeThemes.length} 条主线 · 点击排名联动筛选队列`
    : `已聚焦 ${themeFilter} · 点击标题可收起此区`;

  if (query.isLoading) {
    return <div className="loading-screen"><div className="loading-mark"><Radar /></div><span>正在载入作战台</span></div>;
  }

  if (query.isError || !data || !activeRun || !activeRunKey) {
    return (
      <div className="fatal-state">
        <AlertCircle />
        <strong>数据加载失败</strong>
        <span>{query.error instanceof Error ? query.error.message : "请稍后刷新"}</span>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <TopBar runs={data.runs} activeRun={activeRun} activeRunKey={activeRunKey} onRunChange={handleRunChange} />
      <main className="dashboard-main">
        <SummaryStrip run={activeRun} themes={activeThemes} symbols={activeSymbols} />
        <CollapsibleSection
          className="insight-section"
          title="主线洞察"
          subtitle={insightSubtitle}
          open={insightOpen}
          onToggle={() => setInsightOpen((value) => !value)}
        >
          <div className="market-grid nested-grid">
            <ThemeRanking run={activeRun} themes={activeThemes} selectedTheme={themeFilter} onSelectTheme={setThemeFilter} />
            <ThemeTrendChart runs={data.runs} allThemes={data.themes} selectedThemes={activeThemes} />
          </div>
        </CollapsibleSection>
        <CandidateQueue
          key={activeRunKey}
          symbols={activeSymbols}
          themes={activeThemes}
          theme={themeFilter}
          onThemeChange={setThemeFilter}
          onSelect={setSelectedCandidate}
        />
        <footer className="page-footer">
          <span>10-20个交易日策略周期</span>
          <span>仅用于研究和交易准备，不构成投资建议</span>
          <span>页面更新 {formatDateTime(data.built_at)}</span>
        </footer>
      </main>
      <CandidateDrawer candidate={selectedCandidate} onClose={handleDrawerClose} />
    </div>
  );
}
