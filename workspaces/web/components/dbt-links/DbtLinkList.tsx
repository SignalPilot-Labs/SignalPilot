import type { DbtLinkV1, LinkKind } from "@/lib/dbt-links/types";

const KIND_LABEL: Record<LinkKind, string> = {
  native_upload: "Native upload",
  github: "GitHub",
  dbt_cloud: "dbt Cloud",
};

interface DbtLinkListProps {
  items: DbtLinkV1[];
}

export function DbtLinkList({ items }: DbtLinkListProps) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li
          key={item.id}
          className="block rounded-card border border-border bg-surface p-4 shadow-card"
        >
          <h2 className="text-base font-semibold text-fg">{item.name}</h2>
          <p className="text-sm text-muted mt-1">
            {KIND_LABEL[item.kind]} &middot; {new Date(item.createdAt).toLocaleString()}
          </p>
        </li>
      ))}
    </ul>
  );
}
