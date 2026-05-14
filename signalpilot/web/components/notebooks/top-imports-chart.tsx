import type { ImportCount } from "@/lib/types";

interface TopImportsChartProps {
  imports: ImportCount[];
}

export function TopImportsChart({ imports }: TopImportsChartProps) {
  const items = imports.slice(0, 10);
  const maxCount = items.length > 0 ? items[0].count : 1;

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-4 mb-6" role="img" aria-label={`Top imports chart showing ${items.length} most used modules`}>
      <p className="text-[11px] uppercase tracking-wider text-[var(--color-text-dim)] mb-3">
        top imports
      </p>
      <div className="flex flex-col gap-1.5">
        {items.map((item) => {
          const pct = maxCount > 0 ? (item.count / maxCount) * 100 : 0;
          return (
            <div key={item.name} className="flex items-center gap-3">
              <span
                className="text-[11px] font-mono text-[var(--color-text-muted)] tracking-wider shrink-0 overflow-hidden text-ellipsis whitespace-nowrap"
                style={{ width: "9rem" }}
                title={item.name}
              >
                {item.name}
              </span>
              <div className="flex-1 h-3 bg-[var(--color-bg)] relative overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 transition-[width]"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: "rgba(238,238,238,0.18)",
                  }}
                />
              </div>
              <span className="text-[11px] font-mono text-[var(--color-text-dim)] tracking-wider shrink-0 text-right" style={{ width: "2.5rem" }}>
                {item.count}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
