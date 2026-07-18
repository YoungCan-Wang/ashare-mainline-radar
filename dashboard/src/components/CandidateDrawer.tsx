import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { formatDateTime, formatMetricPercent, formatNumber, formatPercent, formatPrice, formatRatio, formatSignedPercent } from "../lib/format";
import { planSummary, ROLE_LABELS } from "../lib/presentation";
import type { SymbolRow } from "../types";
import { MetricGrid, type MetricItem } from "./MetricGrid";

interface CandidateDrawerProps {
  candidate: SymbolRow | null;
  onClose: () => void;
}

const PAPER_STATUS_LABELS: Record<string, string> = {
  watching: "等待触发",
  triggered: "已触发待成交",
  open: "模拟持仓",
  expired: "到期未触发",
  cancelled: "计划取消",
  closed: "模拟已退出",
};

export function CandidateDrawer({ candidate, onClose }: CandidateDrawerProps) {
  const target = candidate?.target_payload;
  const fundamental = candidate?.fundamental_payload;
  const metrics = candidate?.market_metrics;
  const plan = candidate?.trade_plan;
  const strong = candidate?.signal_payload?.strong_stock;
  const backtest = strong?.backtest;
  const paperPlan = candidate?.paper_trade_plan;
  const shadowPlan = candidate?.shadow_trade_plan;
  const paperStatus = paperPlan ? (PAPER_STATUS_LABELS[paperPlan.status] ?? paperPlan.status) : "尚未生成可执行计划";
  const shadowStatus = shadowPlan ? (PAPER_STATUS_LABELS[shadowPlan.status] ?? shadowPlan.status) : "尚未生成影子计划";

  const targetMetrics: MetricItem[] = [
    { label: "入选价", value: formatPrice(candidate?.first_selected_price) },
    { label: "现价", value: formatPrice(candidate?.latest_price ?? candidate?.last_close) },
    { label: "入选以来", value: formatSignedPercent(candidate?.return_since_selection) },
    { label: "当日涨跌", value: formatSignedPercent(candidate?.daily_change_pct) },
    { label: "目标下沿", value: formatPrice(target?.target_low) },
    { label: "目标上沿", value: formatPrice(target?.target_high) },
  ];
  const trendMetrics: MetricItem[] = [
    { label: "5日涨幅", value: formatPercent(metrics?.ret_5d) },
    { label: "20日涨幅", value: formatPercent(metrics?.ret_20d) },
    { label: "60日位置", value: formatPercent(metrics?.range_position_60d) },
    { label: "成交热度", value: formatRatio(metrics?.amount_ratio ?? metrics?.amount_ratio_5_20) },
    { label: "15日胜率", value: formatPercent(backtest?.win_rate) },
    { label: "15日均值", value: formatPercent(backtest?.avg_return) },
  ];
  const fundamentalMetrics: MetricItem[] = [
    { label: "状态", value: fundamental?.status ?? strong?.fundamental_status ?? "未覆盖" },
    { label: "财务分", value: formatNumber(fundamental?.score ?? strong?.fundamental_score) },
    { label: "营收同比", value: formatMetricPercent(fundamental?.revenue_yoy) },
    { label: "净利同比", value: formatMetricPercent(fundamental?.net_income_yoy) },
    { label: "ROE", value: formatMetricPercent(fundamental?.roe) },
    { label: "PB", value: fundamental?.price_to_book == null ? "--" : `${formatNumber(fundamental.price_to_book, 2)}x` },
  ];

  return (
    <Dialog.Root open={candidate !== null} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-backdrop" />
        <Dialog.Content className="detail-drawer">
          <div className="drawer-header">
            <div>
              <span className="drawer-kicker">{candidate?.symbol ?? "--"}</span>
              <Dialog.Title>{candidate?.name ?? candidate?.symbol ?? "标的详情"}</Dialog.Title>
              <Dialog.Description className="sr-only">标的交易计划、目标赔率、资金趋势和基本面详情</Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button className="icon-button" type="button" title="关闭" aria-label="关闭详情"><X /></button>
            </Dialog.Close>
          </div>
          <div className="drawer-content">
            <div className="drawer-score-line">
              <div><span className="summary-label">优先级</span><div className="drawer-score">{formatNumber(candidate?.priority_score)}</div></div>
              <div className="role-stack">
                {candidate?.roles?.map((role) => <span className="role-badge" key={role}>{ROLE_LABELS[role]}</span>)}
              </div>
            </div>
            <div className="action-panel">{candidate?.action_state ?? (candidate ? planSummary(candidate) : "") ?? "继续观察"}</div>
            <section className="drawer-section">
              <h3>交易计划</h3>
              <dl className="detail-list">
                <div className="detail-row"><dt>所属主线</dt><dd>{candidate?.primary_theme ?? candidate?.themes?.join("、") ?? "未映射"}</dd></div>
                <div className="detail-row"><dt>首次入选</dt><dd>{formatDateTime(candidate?.first_selected_at)} · {formatPrice(candidate?.first_selected_price)}</dd></div>
                <div className="detail-row"><dt>模拟状态</dt><dd>{paperStatus}</dd></div>
                <div className="detail-row"><dt>冻结影子</dt><dd>{shadowStatus}{shadowPlan?.status === "open" || shadowPlan?.status === "closed" ? ` · ${formatSignedPercent(shadowPlan.net_return)}` : ""}</dd></div>
                <div className="detail-row"><dt>触发与成交</dt><dd>{paperPlan ? `${paperPlan.trigger_date ? `${paperPlan.trigger_date} 触发` : "尚未触发"} · ${paperPlan.entry_date ? `${paperPlan.entry_date} 以 ${formatPrice(paperPlan.entry_price)} 模拟成交` : "尚未成交"}` : "--"}</dd></div>
                <div className="detail-row"><dt>持仓估值</dt><dd>{paperPlan?.status === "open" ? `${paperPlan.mark_date ?? "--"} 按 ${formatPrice(paperPlan.mark_price)} 估值 · 扣费净收益 ${formatSignedPercent(paperPlan.net_return)}` : "--"}</dd></div>
                <div className="detail-row"><dt>退出结果</dt><dd>{paperPlan?.status === "closed" ? `${paperPlan.exit_date ?? "--"} 退出 · 净收益 ${formatSignedPercent(paperPlan.net_return)}${paperPlan.exit_delay_days ? ` · 延迟 ${paperPlan.exit_delay_days} 日成交` : ""}` : (paperPlan?.exit_reason ?? "尚未退出")}</dd></div>
                <div className="detail-row"><dt>影子退出</dt><dd>{shadowPlan?.status === "closed" ? `${shadowPlan.exit_date ?? "--"} 退出 · 净收益 ${formatSignedPercent(shadowPlan.net_return)}` : (shadowPlan?.exit_reason ?? "连续3日失效或到期退出")}</dd></div>
                <div className="detail-row"><dt>行情时间</dt><dd>{formatDateTime(candidate?.quote_at ?? candidate?.quote_refreshed_at)}</dd></div>
                <div className="detail-row"><dt>参与条件</dt><dd>{plan?.entry_plan ?? plan?.confirmation ?? "等待条件确认"}</dd></div>
                <div className="detail-row"><dt>失效条件</dt><dd>{plan?.invalidation ?? (target?.stop_price == null ? "未覆盖" : `跌破 ${formatPrice(target.stop_price)}`)}</dd></div>
                <div className="detail-row"><dt>仓位提示</dt><dd>{plan?.position_note ?? "按市场闸门与计划仓位执行"}</dd></div>
                <div className="detail-row"><dt>目标周期</dt><dd>{target?.horizon ?? "10-20个交易日"}</dd></div>
              </dl>
            </section>
            <section className="drawer-section"><h3>目标与赔率</h3><MetricGrid items={targetMetrics} /></section>
            <section className="drawer-section"><h3>趋势与资金</h3><MetricGrid items={trendMetrics} /></section>
            <section className="drawer-section"><h3>基本面兑现</h3><MetricGrid items={fundamentalMetrics} /></section>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
