import * as Tabs from "@radix-ui/react-tabs";
import { ChevronRight, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { formatDateTime, formatPrice, formatSignedPercent, returnTone, shortDate } from "../lib/format";
import { planSummary, ROLE_LABELS } from "../lib/presentation";
import type { RadarRole, SymbolRow, ThemeRow } from "../types";
import { SortableHeader, type SortDirection, type SortKey } from "./SortableHeader";

type RoleFilter = "all" | "waiting" | RadarRole;

interface SortState {
  key: SortKey | "priority";
  direction: SortDirection;
}

const ROLE_DEFINITIONS: ReadonlyArray<{ id: RoleFilter; label: string }> = [
  { id: "all", label: "全部" },
  { id: "next_buy", label: "建仓候选" },
  { id: "strong_stock", label: "持有观察" },
  { id: "waiting", label: "等待确认" },
  { id: "golden_pit", label: "黄金坑" },
  { id: "accumulation", label: "低位资金" },
  { id: "monthly_base", label: "月线箱体" },
] as const;

const PAPER_STATUS_LABELS: Record<string, string> = {
  watching: "等待触发",
  triggered: "已触发待成交",
  open: "模拟持仓",
  expired: "到期未触发",
  cancelled: "计划取消",
  closed: "模拟已退出",
};

function roleMatches(row: SymbolRow, role: RoleFilter): boolean {
  if (role === "all") return true;
  if (role === "waiting") {
    const plan = row.trade_plan;
    const text = `${row.action_state ?? ""} ${plan?.decision ?? ""} ${plan?.entry_plan ?? ""} ${plan?.confirmation ?? ""}`;
    return /等待|确认|回踩|观察/.test(text);
  }
  return row.roles?.includes(role) ?? false;
}

function sortableValue(row: SymbolRow, key: SortKey): number | undefined {
  if (key === "selected_at") {
    const timestamp = Date.parse(row.first_selected_at ?? row.first_market_date ?? "");
    return Number.isNaN(timestamp) ? undefined : timestamp;
  }
  if (key === "selected_price") return row.first_selected_price;
  if (key === "latest_price") return row.latest_price ?? row.last_close;
  if (key === "selection_return") return row.return_since_selection;
  if (key === "strategy_return") return row.paper_trade_plan?.net_return;
  if (key === "shadow_return") return row.shadow_trade_plan?.net_return;
  return row.daily_change_pct;
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
  const [sortState, setSortState] = useState<SortState>({ key: "priority", direction: "desc" });

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
      if (sortState.key === "priority") return (b.priority_score ?? 0) - (a.priority_score ?? 0);
      const aValue = sortableValue(a, sortState.key);
      const bValue = sortableValue(b, sortState.key);
      if (aValue == null && bValue == null) {
        return (b.priority_score ?? 0) - (a.priority_score ?? 0) || a.symbol.localeCompare(b.symbol);
      }
      if (aValue == null) return 1;
      if (bValue == null) return -1;
      const comparison = sortState.direction === "desc" ? bValue - aValue : aValue - bValue;
      return comparison || (b.priority_score ?? 0) - (a.priority_score ?? 0) || a.symbol.localeCompare(b.symbol);
    });
  }, [symbols, role, theme, search, sortState]);
  const latestQuoteRefresh = useMemo(
    () => symbols.reduce<string | undefined>((latest, row) => {
      if (!row.quote_refreshed_at) return latest;
      return !latest || row.quote_refreshed_at > latest ? row.quote_refreshed_at : latest;
    }, undefined),
    [symbols],
  );
  const handleSort = (key: SortKey) => {
    setSortState((current) => ({
      key,
      direction: current.key === key && current.direction === "desc" ? "asc" : "desc",
    }));
  };

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
          <thead>
            <tr>
              <th scope="col">标的</th>
              <th scope="col">所属主线</th>
              <SortableHeader label="入选时间" sortKey="selected_at" activeKey={sortState.key} direction={sortState.direction} onSort={handleSort} />
              <SortableHeader label="入选价" sortKey="selected_price" activeKey={sortState.key} direction={sortState.direction} onSort={handleSort} />
              <SortableHeader label="现价" sortKey="latest_price" activeKey={sortState.key} direction={sortState.direction} onSort={handleSort} />
              <SortableHeader label="入选涨跌" sortKey="selection_return" activeKey={sortState.key} direction={sortState.direction} onSort={handleSort} />
              <SortableHeader label="当日涨跌" sortKey="daily_return" activeKey={sortState.key} direction={sortState.direction} onSort={handleSort} />
              <th scope="col">模拟状态</th>
              <SortableHeader label="策略收益" sortKey="strategy_return" activeKey={sortState.key} direction={sortState.direction} onSort={handleSort} />
              <SortableHeader label="3日影子" sortKey="shadow_return" activeKey={sortState.key} direction={sortState.direction} onSort={handleSort} />
              <th scope="col">当前动作</th>
              <th scope="col">目标区间</th>
              <th scope="col">信号身份</th>
              <th scope="col"><span className="sr-only">详情</span></th>
            </tr>
          </thead>
          <tbody>
            {filteredSymbols.map((row) => {
              const target = row.target_payload;
              const targetRange = target?.target_low == null && target?.target_high == null ? "--" : `${formatPrice(target.target_low)} - ${formatPrice(target.target_high)}`;
              const selectionTime = row.first_selected_at ? formatDateTime(row.first_selected_at) : shortDate(row.first_market_date);
              const paperPlan = row.paper_trade_plan;
              const shadowPlan = row.shadow_trade_plan;
              return (
                <tr key={`${row.run_key}:${row.symbol}`}>
                  <td><div className="symbol-name">{row.name ?? row.symbol}</div><div className="symbol-code">{row.symbol}</div></td>
                  <td>{row.primary_theme ?? row.themes?.[0] ?? "未映射"}</td>
                  <td className="numeric selection-time">{selectionTime}</td>
                  <td className="numeric">{formatPrice(row.first_selected_price)}</td>
                  <td className="numeric current-price">{formatPrice(row.latest_price ?? row.last_close)}</td>
                  <td className={`numeric return-value ${returnTone(row.return_since_selection)}`}>{formatSignedPercent(row.return_since_selection)}</td>
                  <td className={`numeric return-value ${returnTone(row.daily_change_pct)}`}>{formatSignedPercent(row.daily_change_pct)}</td>
                  <td className="paper-status">{paperPlan ? (PAPER_STATUS_LABELS[paperPlan.status] ?? paperPlan.status) : "未生成计划"}</td>
                  <td className={`numeric return-value ${returnTone(paperPlan?.net_return)}`}>{paperPlan?.status === "open" || paperPlan?.status === "closed" ? formatSignedPercent(paperPlan.net_return) : "--"}</td>
                  <td className={`numeric return-value ${returnTone(shadowPlan?.net_return)}`}>{shadowPlan?.status === "open" || shadowPlan?.status === "closed" ? formatSignedPercent(shadowPlan.net_return) : "--"}</td>
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
