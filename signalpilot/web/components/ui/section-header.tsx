import React from "react";

export function SectionHeader({
  icon: Icon,
  title,
  iconColor,
}: {
  icon: React.ElementType;
  title: string;
  iconColor?: string;
}) {
  return (
    <div className="section-header mb-4">
      <div className="flex items-center gap-2">
        <Icon
          className={`w-3.5 h-3.5 ${iconColor || "text-[var(--color-text-dim)]"}`}
          strokeWidth={1.5}
        />
        <span className="text-[12px] text-[var(--color-text-dim)] uppercase tracking-[0.15em]">
          {title}
        </span>
      </div>
    </div>
  );
}
