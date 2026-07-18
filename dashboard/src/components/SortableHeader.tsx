import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

export type SortDirection = "asc" | "desc";
export type SortKey = "selected_at" | "selected_price" | "latest_price" | "selection_return" | "daily_return" | "strategy_return";

interface SortableHeaderProps {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey | "priority";
  direction: SortDirection;
  onSort: (key: SortKey) => void;
}

export function SortableHeader({ label, sortKey, activeKey, direction, onSort }: SortableHeaderProps) {
  const isActive = activeKey === sortKey;
  const SortIcon = !isActive ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  const ariaSort = !isActive ? "none" : direction === "asc" ? "ascending" : "descending";

  return (
    <th scope="col" aria-sort={ariaSort}>
      <button
        className="sortable-header-button"
        data-active={isActive || undefined}
        type="button"
        title={`${label}排序`}
        onClick={() => onSort(sortKey)}
      >
        <span>{label}</span>
        <SortIcon aria-hidden="true" />
      </button>
    </th>
  );
}
