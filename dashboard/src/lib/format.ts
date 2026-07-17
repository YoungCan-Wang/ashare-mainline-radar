export function numberValue(value: number | undefined, fallback = 0): number {
  return value != null && Number.isFinite(value) ? value : fallback;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function formatNumber(value: number | undefined, digits = 1): string {
  return value != null && Number.isFinite(value) ? value.toFixed(digits) : "--";
}

export function formatInteger(value: number | undefined): string {
  return value != null && Number.isFinite(value)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value)
    : "--";
}

export function formatPrice(value: number | undefined): string {
  return value != null && Number.isFinite(value) ? value.toFixed(2) : "--";
}

export function formatPercent(value: number | undefined): string {
  return value != null && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "--";
}

export function formatSignedPercent(value: number | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--";
  const percent = value * 100;
  return `${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
}

export function returnTone(value: number | undefined): "positive" | "negative" | "neutral" {
  if (value == null || value === 0) return "neutral";
  return value > 0 ? "positive" : "negative";
}

export function formatMetricPercent(value: number | undefined): string {
  return value != null && Number.isFinite(value) ? `${value.toFixed(1)}%` : "--";
}

export function formatRatio(value: number | undefined): string {
  return value != null && Number.isFinite(value) ? `${value.toFixed(2)}x` : "--";
}

export function shortDate(value: string | undefined): string {
  const parts = value?.split("-") ?? [];
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : value ?? "--";
}

export function formatDateTime(value: string | undefined): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}
