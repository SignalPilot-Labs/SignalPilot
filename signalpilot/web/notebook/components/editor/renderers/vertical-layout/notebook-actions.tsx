import { useAtomValue } from "jotai";
import {
  Check,
  Code2Icon,
  CodeIcon,
  FolderDownIcon,
  ImageIcon,
  MoreHorizontalIcon,
} from "lucide-react";
import type React from "react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { viewerOnlyAtom } from "@/core/mode";
import { useRequestClient } from "@/core/network/requests";
import { downloadAsHTML } from "@/core/static/download-html";
import { isStaticNotebook } from "@/core/static/static-state";
import { cn } from "@/utils/cn";
import {
  ADD_PRINTING_CLASS,
  downloadBlob,
  downloadHTMLAsImage,
} from "@/utils/download";
import { Filenames } from "@/utils/filenames";

/**
 * Notebook-level actions menu for the read view: show code, download as
 * HTML, .py, and PNG. Hidden on pure viewer surfaces (the chat live notebook
 * panel and its pop-out): they own their Code/App toggle, run in a sandbox
 * with no static export, and the chat page hosts the notebook chrome.
 */
export const NotebookActionButtons: React.FC<{
  canShowCode: boolean;
  showCode: boolean;
  onToggleShowCode: () => void;
}> = ({ canShowCode, showCode, onToggleShowCode }) => {
  const { readCode } = useRequestClient();
  const viewerOnly = useAtomValue(viewerOnlyAtom);

  const handleDownloadAsPNG = async () => {
    const app = document.getElementById("App");
    if (!app) {
      return;
    }
    await downloadHTMLAsImage({
      element: app,
      filename: document.title,
      // Add body.printing ONLY when converting the whole notebook to a screenshot
      prepare: ADD_PRINTING_CLASS,
    });
  };

  const handleDownloadAsHTML = async () => {
    const app = document.getElementById("App");
    if (!app) {
      return;
    }
    await downloadAsHTML({ filename: document.title, includeCode: true });
  };

  const handleDownloadAsPython = async () => {
    const code = await readCode();
    downloadBlob(
      new Blob([code.contents], { type: "text/plain" }),
      Filenames.toPY(document.title),
    );
  };

  const isStatic = isStaticNotebook();
  const actions: React.ReactNode[] = [];

  if (viewerOnly) {
    return null;
  }

  if (canShowCode) {
    actions.push(
      <DropdownMenuItem
        onSelect={onToggleShowCode}
        data-testid="notebook-action-show-code"
        key="show-code"
      >
        <Code2Icon className="mr-2" size={14} strokeWidth={1.5} />
        <span className="flex-1">Show code</span>
        {showCode && <Check className="h-4 w-4" />}
      </DropdownMenuItem>,
      <DropdownMenuSeparator key="show-code-separator" />,
    );
  }

  if (!isStatic) {
    actions.push(
      <DropdownMenuItem
        onSelect={handleDownloadAsHTML}
        data-testid="notebook-action-download-html"
        key="download-html"
      >
        <FolderDownIcon className="mr-2" size={14} strokeWidth={1.5} />
        Download as HTML
      </DropdownMenuItem>,
    );

    // Only show download as Python if code is available
    if (canShowCode) {
      actions.push(
        <DropdownMenuItem
          onSelect={handleDownloadAsPython}
          data-testid="notebook-action-download-python"
          key="download-python"
        >
          <CodeIcon className="mr-2" size={14} strokeWidth={1.5} />
          Download as .py
        </DropdownMenuItem>,
      );
    }

    actions.push(
      <DropdownMenuSeparator key="download-separator" />,
      <DropdownMenuItem
        onSelect={handleDownloadAsPNG}
        data-testid="notebook-action-download-png"
        key="download-png"
      >
        <ImageIcon className="mr-2" size={14} strokeWidth={1.5} />
        Download as PNG
      </DropdownMenuItem>,
    );
  }

  if (actions.length === 0) {
    return null;
  }

  // Don't change the id of this element
  // as this may be used in custom css to hide/show the actions dropdown
  return (
    <div
      data-testid="notebook-actions-dropdown"
      className={cn(
        "right-0 top-0 z-50 m-4 print:hidden flex gap-2",
        // If the notebook is static, we have a banner at the top, so
        // we can't use fixed positioning. Ideally this is sticky, but the
        // current dom structure makes that difficult.
        isStaticNotebook() ? "absolute" : "fixed",
      )}
    >
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild={true}>
          <Button variant="secondary" size="xs">
            <MoreHorizontalIcon className="w-4 h-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="print:hidden w-[220px]">
          {actions}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};
