import * as Tabs from "@radix-ui/react-tabs";
import { ArrowDownUp, ChevronRight, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { formatDateTime, formatPrice, formatSignedPercent, returnTone, shortDate } from "../lib/format";
import { planSummary, ROLE_LABELS } from "../lib/presentation";
import type { RadarRole, SymbolRow, ThemeRow } from "../types";

type RoleFilter = "all" | "waiting" | RadarRole;
type SortOrder = "priority" | "return_desc" | "return_asc";

const ROLE_DEFINITIONS: ReadonlyArray<{ id: RoleFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "next_buy", label: "建仓候选" },
  { id: "strong_stock", label: "持有观察" },
  { id: "waiting", label: "等待确认" },
  { id: "golden_pit", label: "黄金坑" },
  { id: "accumulation", label: "低位资金" },
  { id: "monthly_base", label: "月线箱体" },
] as const;

function roleMatches(row: SymbolRow, role: RoleFilter): boolean {
  if (role === "all") return true;
  if (role === "waiting") {
    const plan = row.trade_plan;
    const text = `${row.action_state ?? ""} ${plan?.decision ?? ""} ${plan?.entry_plan ?? ""} ${plan?.confirmation ?? ""}`;
    return /等待|确认|回踩|观察/.test(text);
  }
  return row.roles?.includes(role) ?? false;
}

interface CandidateQueueProps {
  symbols: SymbolRow[];
  themes: ThemeRow[];
  onSelect: (candidate: SymbolRow) => void;
}

export function CandidateQueue({ symbols, themes, onSelect }: CandidateQueueProps) {
  const [role, setRole] = useState<RoleFilter>("all");
  const [theme, setTheme] = useState("all");
  const [search, setSearch] = useState("");
  const [sortOrder, setSortOrder] = useState<SortOrder>("priority");

  const roleCounts = useMemo(
    () => new Map(ROLE_DEFINITIONS.map((definition) => [definition.id, symbols.filter((row) => roleMatches(row, definition.id)).length])),
    [symbols],
  );
  const filteredSymbols = useMemo(() => {
    const query = search.trim().toLowerCase();
    const filtered = symbols
      .filter((row) => roleMatches(row, role))
      .filter((row) => theme === "all" || row.primary_theme === theme || row.themes?.includes(theme))
      .filter((row) => !query || `${row.symbol} ${row.name ?? ""}`.toLowerCase().includes(query));
    return filtered.sort((a, b) => {
      if (sortOrder === "priority") return (b.priority_score ?? 0) - (a.priority_score ?? 0);
      const aReturn = a.return_since_selection;
      const bReturn = b.return_since_selection;
      if (aReturn == null) return 1;
      if (bReturn == null) return -1;
      return sortOrder === "return_desc" ? bReturn - aReturn : aReturn - bReturn;
    });
  }, [symbols, role, theme, search, sortOrder]);
  const latestQuoteRefresh = useMemo(
    () => symbols.reduce<string | undefined>((latest, row) => {
      if (!row.quote_refreshed_at) return latest;
      return !latest || row.quote_refreshed_at > latest ? row.quote_refreshed_at : latest;
    }, undefined),
    [symbols],
  );

  return (
    <section className="section-block candidates-block">
      <div className="section-header candidates-header">
        <div><h2>标的作战队列</h2><p>显示 {filteredSymbols.length} / {symbols.length} 只 · 现价更新 {formatDateTime(latestQuoteRefresh)}</p></div>
        <div className="filter-controls">
          <label className="search-control">
            <Search aria-hidden="true" />
            <span className="sr-only">搜索代码或名称</span>
            <input type="search" placeholder="代码或名称" value={search} onChange={(event) => setSearch(event.target.value)} />
          </label>
          <select className="select-control" aria-label="筛选主线" value={theme} onChange={(event) => setTheme(event.target.value)}>
            <option value="all">全部主线</option>
            {themes.map((row) => <option key={row.theme} value={row.theme}>{row.theme}</option>)}
          </select>
          <label className="sort-control">
            <ArrowDownUp aria-hidden="true" />
            <span className="sr-only">排序方式</span>
            <select className="select-control" aria-label="排序方式" value={sortOrder} onChange={(event) => setSortOrder(event.target.value as SortOrder)}>
              <option value="priority">按优先级</option>
              <option value="return_desc">涨幅从高到低</option>
              <option value="return_asc">涨幅从低到高</option>
            </select>
          </label>
        </div>
      </div>
      <Tabs.Root value={role} onValueChange={(value) => setRole(value as RoleFilter)}>
        <Tabs.List className="role-tabs" aria-label="标的类型">
          {ROLE_DEFINITIONS.map((definition) => (
            <Tabs.Trigger className="role-tab" key={definition.id} value={definition.id}>
              {definition.label}<span className="role-count">{roleCounts.get(definition.id) ?? 0}</span>
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </Tabs.Root>
      <div className="table-scroll">
        <table className="data-table candidate-table">
          <thead><tr><th>标的</th><th>所属主线</th><th>入选时间</th><th>入选价</th><th>现价</th><th>入选涨跌</th><th>当日涨跌</th><th>当前动作</th><th>目标区间</th><th>信号身份</th><th><span className="sr-only">详情</span></th></tr></thead>
          <tbody>
            {filteredSymbols.map((row) => {
              const target = row.target_payload;
              const targetRange = target?.target_low == null && target?.target_high == null ? "--" : `${formatPrice(target.target_low)} - ${formatPrice(target.target_high)}`;
              const selectionTime = row.first_selected_at ? formatDateTime(row.first_selected_at) : shortDate(row.first_market_date);
              return (
                <tr key={`${row.run_key}:${row.symbol}`}>
                  <td><div className="symbol-name">{row.name ?? row.symbol}</div><div className="symbol-code">{row.symbol}</div></td>
                  <td>{row.primary_theme ?? row.themes?.[0] ?? "未映射"}</td>
                  <td className="numeric selection-time">{selectionTime}</td>
                  <td className="numeric">{formatPrice(row.first_selected_price)}</td>
                  <td className="numeric current-price">{formatPrice(row.latest_price ?? row.last_close)}</td>
                  <td className={`numeric return-value ${returnTone(row.return_since_selection)}`}>{formatSignedPercent(row.return_since_selection)}</td>
                  <td className={`numeric return-value ${returnTone(row.daily_change_pct)}`}>{formatSignedPercent(row.daily_change_pct)}</td>
                  <td className="action-cell"><span className="action-text">{row.action_state ?? (planSummary(row) || "继续观察")}</span></td>
                  <td className="numeric">{targetRange}</td>
                  <td><div className="role-stack">{row.roles?.slice(0, 4).map((item) => <span className="role-badge" key={item}>{ROLE_LABELS[item]}</span>)}</div></td>
                  <td><button className="details-button" type="button" title="查看详情" aria-label={`查看 ${row.name ?? row.symbol} 详情`} onClick={() => onSelect(row)}><ChevronRight /></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {filteredSymbols.length === 0 ? <div className="empty-state visible">当前筛选没有标的</div> : null}
    </section>
  );
}
