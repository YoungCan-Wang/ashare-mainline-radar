import type { SymbolRow } from "../types";

export const ROLE_LABELS: Readonly<Record<string, string>> = {
  next_buy: "建仓",
  strong_stock: "强势",
  golden_pit: "黄金坑",
  accumulation: "低位资金",
  monthly_base: "月线箱体",
  expectation_gap: "预期差",
  leader_tape: "龙头带",
  market_watchlist: "观察池",
};

export function planSummary(row: SymbolRow): string {
  const plan = row.trade_plan;
  return plan?.decision ?? plan?.action ?? plan?.entry_plan ?? plan?.confirmation ?? "";
}

export function gateLabel(level: string | undefined): string {
  return {
    green: "允许参与",
    yellow: "控制仓位",
    orange: "控制仓位",
    red: "暂停新仓",
  }[level ?? ""] ?? "闸门待确认";
}

export function gateColor(level: string | undefined): string {
  return {
    green: "var(--gate-green)",
    yellow: "var(--gate-amber)",
    orange: "var(--gate-amber)",
    red: "var(--gate-red)",
  }[level ?? ""] ?? "var(--text)";
}

export function gateTone(level: string | undefined): string {
  return { green: "green", yellow: "yellow", orange: "yellow", red: "red" }[level ?? ""] ?? "neutral";
}

export function themeTone(stage: string | undefined, status: string | undefined): string {
  const text = `${stage ?? ""}${status ?? ""}`;
  if (/退潮|风险|破位/.test(text)) return "red";
  if (/触发|主升|成立|延续|确认/.test(text)) return "green";
  if (/回踩|试探|候选|等待/.test(text)) return "yellow";
  return "neutral";
}
