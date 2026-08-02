import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

interface CollapsibleSectionProps {
  title: string;
  subtitle?: string;
  open: boolean;
  onToggle: () => void;
  trailing?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** 区块级收起/展开：像 Android ExpandableListView 的 group header */
export function CollapsibleSection({
  title,
  subtitle,
  open,
  onToggle,
  trailing,
  children,
  className = "",
}: CollapsibleSectionProps) {
  return (
    <section className={`section-block collapsible-section ${className}`.trim()}>
      <button
        type="button"
        className="collapsible-header"
        aria-expanded={open}
        onClick={onToggle}
      >
        <div className="collapsible-heading">
          <span className={`collapsible-chevron${open ? " open" : ""}`} aria-hidden="true">
            <ChevronDown />
          </span>
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </div>
        {trailing ? (
          <div className="header-actions" onClick={(event) => event.stopPropagation()}>
            {trailing}
          </div>
        ) : null}
      </button>
      {open ? <div className="collapsible-body">{children}</div> : null}
    </section>
  );
}
