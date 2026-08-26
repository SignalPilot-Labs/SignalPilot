import { type DOMNode, Element, Text } from "html-react-parser";
import {
  BugPlayIcon,
  ChevronDown,
  CopyIcon,
  ExternalLinkIcon,
  MessageCircleIcon,
  SearchIcon,
} from "lucide-react";
import { type JSX, useState } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip } from "@/components/ui/tooltip";
import { getCellEditorView } from "@/core/cells/cells";
import type { CellId } from "@/core/cells/ids";
import { SCRATCH_CELL_ID } from "@/core/cells/ids";
import { insertDebuggerAtLine } from "@/core/codemirror/editing/debugging";
import { getRequestClient } from "@/core/network/requests";
import { isStaticNotebook } from "@/core/static/static-state";

import { renderHTML } from "@/plugins/core/RenderHTML";
import { sanitizeHtml } from "@/plugins/core/sanitize-html";
import { copyToClipboard } from "@/utils/copy";
import {
  elementContainsCellFile,
  extractAllTracebackInfo,
  getTracebackInfo,
} from "@/utils/traceback";
import { cn } from "../../../utils/cn";
import { CellLinkTraceback } from "../links/cell-link";

interface Props {
  cellId: CellId | undefined;
  traceback: string;
}

const KEY = "item";

/**
 * List of errors due to violations of output semantics.
 */
export const SpTracebackOutput = ({
  traceback,
  cellId,
}: Props): JSX.Element => {
  const htmlTraceback = renderHTML({
    html: traceback,
    additionalReplacements: [replaceTracebackFilenames, replaceTracebackPrefix],
  });
  const [expanded, setExpanded] = useState(true);

  const lastTracebackLine = lastLine(traceback);

  // Get last traceback info
  const tracebackInfo = extractAllTracebackInfo(traceback)?.at(0);

  // Don't show in wasm, static notebooks, or scratchpad
  const showDebugger =
    tracebackInfo &&
    tracebackInfo.kind === "cell" &&
    !isStaticNotebook() &&
    cellId !== SCRATCH_CELL_ID;

  const showSearch = !isStaticNotebook();

  const [error, errorMessage] = lastTracebackLine.split(":", 2);

  return (
    <div className="flex flex-col gap-2 min-w-full w-fit">
      <Accordion type="single" collapsible={true} value={expanded ? KEY : ""}>
        <AccordionItem value={KEY} className="border-none">
          <div
            className="flex gap-2 h-10 px-2 hover:bg-muted rounded-sm select-none items-center cursor-pointer transition-all"
            onClick={() => setExpanded((prev) => !prev)}
          >
            <ChevronDown
              className={cn(
                "h-4 w-4 text-muted-foreground transition-transform duration-200 shrink-0",
                expanded ? "rotate-180" : "rotate-0",
              )}
            />
            <div className="text-sm inline font-mono">
              <span className="text-destructive">{error || "Error"}:</span>{" "}
              {errorMessage}
            </div>
          </div>
          <AccordionContent className="text-muted-foreground px-4 pt-2 text-xs overflow-auto">
            {htmlTraceback}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
      <div className="flex gap-2">
        {showDebugger && (
          <Tooltip content={"Attach pdb to the exception point."}>
            <Button
              size="xs"
              variant="outline"
              onClick={() => {
                getRequestClient().sendPdb({ cellId: tracebackInfo.cellId });
              }}
            >
              <BugPlayIcon className="h-3 w-3 mr-2" />
              Launch debugger
            </Button>
          </Tooltip>
        )}
        {showSearch && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild={true}>
              <Button size="xs" variant="text">
                Get help
                <ChevronDown className="h-3 w-3 ml-1" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem asChild={true}>
                <a
                  target="_blank"
                  href={`https://www.google.com/search?q=${encodeURIComponent(lastTracebackLine)}`}
                  rel="noreferrer"
                >
                  <SearchIcon className="h-4 w-4 mr-2" />
                  Search on Google
                  <ExternalLinkIcon className="h-3 w-3 ml-auto" />
                </a>
              </DropdownMenuItem>
              <DropdownMenuItem asChild={true}>
                <a
                  target="_blank"
                  href="https://docs.signalpilot.ai/docs/"
                  rel="noopener"
                >
                  <MessageCircleIcon className="h-4 w-4 mr-2" />
                  Ask in Discord
                  <ExternalLinkIcon className="h-3 w-3 ml-auto" />
                </a>
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  // Strip HTML from the traceback (sanitize first to prevent XSS)
                  const div = document.createElement("div");
                  div.innerHTML = sanitizeHtml(traceback);
                  const textContent = div.textContent || "";
                  copyToClipboard(textContent);
                }}
              >
                <CopyIcon className="h-4 w-4 mr-2" />
                Copy to clipboard
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  );
};

function lastLine(text: string): string {
  const el = document.createElement("div");
  el.innerHTML = sanitizeHtml(text);
  const lines = el.textContent?.split("\n").filter(Boolean);
  return lines?.at(-1) || "";
}

export const replaceTracebackFilenames = (domNode: DOMNode) => {
  const info = getTracebackInfo(domNode);
  if (info?.kind === "cell") {
    const tooltipContent = <InsertBreakpointContent />;
    return (
      <span className="nb">
        <span className="inline-flex items-center">
          <CellLinkTraceback
            cellId={info.cellId}
            lineNumber={info.lineNumber}
          />
          <Tooltip content={tooltipContent}>
            <button
              type="button"
              className="ml-1 p-1 rounded-sm hover:bg-muted transition-all inline"
            >
              <BugPlayIcon
                onClick={() => {
                  const view = getCellEditorView(info.cellId);
                  if (view) {
                    insertDebuggerAtLine(view, info.lineNumber);
                  }
                }}
                className="h-3 w-3"
              />
            </button>
          </Tooltip>
        </span>
      </span>
    );
  }
  if (info?.kind === "file") {
    return (
      <div
        className="inline-block cursor-pointer text-destructive hover:underline"
        onClick={(_) => {
          getRequestClient().openFile({
            path: info.filePath,
            lineNumber: info.lineNumber,
          });
        }}
      >
        <span className="nb">"{info.filePath}"</span>
      </div>
    );
  }
};

export const replaceTracebackPrefix = (domNode: DOMNode) => {
  if (
    domNode instanceof Text &&
    domNode.nodeValue?.includes("File") &&
    domNode.next instanceof Element &&
    elementContainsCellFile(domNode.next)
  ) {
    return <>{domNode.nodeValue.replace("File", "Cell")}</>;
  }
};

const InsertBreakpointContent = () => {
  return (
    <>
      Insert a <Kbd className="inline">breakpoint()</Kbd> at this line
    </>
  );
};
