import { DatabaseIcon, FileCodeIcon, FileTextIcon, XIcon } from "lucide-react";
import React from "react";
import {
  activateTab,
  closeTab,
  type FileTab,
  useActiveTabId,
  useOpenTabs,
} from "@/core/file-tabs";
import { openNotebook } from "@/utils/links";
import { cn } from "@/utils/cn";

const FILE_ICONS: Record<string, React.ReactNode> = {
  ".sql": <DatabaseIcon size={12} className="text-emerald-500" />,
  ".py": <FileCodeIcon size={12} className="text-blue-400" />,
  ".yml": <FileTextIcon size={12} className="text-amber-400" />,
  ".yaml": <FileTextIcon size={12} className="text-amber-400" />,
  ".json": <FileTextIcon size={12} className="text-yellow-400" />,
  ".toml": <FileTextIcon size={12} className="text-orange-400" />,
  ".md": <FileTextIcon size={12} className="text-gray-400" />,
};

function getFileIcon(name: string): React.ReactNode {
  const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
  return FILE_ICONS[ext] || <FileTextIcon size={12} className="text-gray-400" />;
}

export const TabBar: React.FC = () => {
  const tabs = useOpenTabs();
  const activeTabId = useActiveTabId();

  if (tabs.length === 0) {return null;}

  return (
    <div className="flex items-center border-b border-border bg-card overflow-x-auto shrink-0">
      {tabs.map((tab) => (
        <TabItem
          key={tab.id}
          tab={tab}
          isActive={tab.id === activeTabId}
          onClose={() => closeTab(tab.id)}
        />
      ))}
    </div>
  );
};

const TabItem: React.FC<{
  tab: FileTab;
  isActive: boolean;
  onClose: () => void;
}> = ({ tab, isActive, onClose }) => {
  const handleClick = () => {
    activateTab(tab.id);
    if (tab.type === "notebook") {
      // Notebooks navigate via URL for session isolation
      openNotebook(tab.path);
    }
    // Raw files: activeTab change triggers RawFileEditor swap in EditApp
  };

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono cursor-pointer border-r border-border/50 shrink-0 max-w-[200px] group",
        isActive
          ? "bg-background text-foreground border-b-2 border-b-primary -mb-px"
          : "bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
      onClick={handleClick}
    >
      {getFileIcon(tab.name)}
      <span className="truncate">{tab.name}</span>
      <button
        type="button"
        className={cn(
          "ml-auto p-0.5 rounded hover:bg-muted/50 shrink-0 transition-opacity",
          isActive
            ? "opacity-60 hover:opacity-100"
            : "opacity-0 group-hover:opacity-60 hover:!opacity-100",
        )}
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
      >
        <XIcon size={10} />
      </button>
    </div>
  );
};
