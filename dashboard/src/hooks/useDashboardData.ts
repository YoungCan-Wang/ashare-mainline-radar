import { useQuery } from "@tanstack/react-query";

import type { DashboardData } from "../types";

async function fetchDashboardData({ signal }: { signal: AbortSignal }): Promise<DashboardData> {
  const response = await fetch("./data.json", { cache: "no-store", signal });
  if (!response.ok) throw new Error(`数据请求失败：HTTP ${response.status}`);
  const data = (await response.json()) as DashboardData;
  if (!Array.isArray(data.runs) || data.runs.length === 0) throw new Error("没有可展示的运行记录");
  return data;
}

export function useDashboardData() {
  return useQuery({
    queryKey: ["radar-dashboard-data"],
    queryFn: fetchDashboardData,
    staleTime: 5 * 60 * 1000,
  });
}
