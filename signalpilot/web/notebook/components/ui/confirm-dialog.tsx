import { AlertTriangleIcon, XIcon } from "lucide-react";
import React, { useCallback, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import { usePortalContainer } from "@/embed/portal-container";

interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "destructive";
  children?: React.ReactNode;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  onConfirm,
  onCancel,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  children,
}) => {
  const portalContainer = usePortalContainer();

  if (!open) {return null;}

  const isDestructive = variant === "destructive";

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-sm mx-4 rounded-xl border border-border bg-background shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={cn(
          "flex items-center gap-3 px-5 py-3 border-b",
          isDestructive ? "border-destructive/20 bg-destructive/5" : "border-border bg-muted/30",
        )}>
          {isDestructive && (
            <AlertTriangleIcon size={18} className="text-destructive shrink-0" />
          )}
          <h3 className="text-sm font-semibold text-foreground flex-1">{title}</h3>
          <button type="button" onClick={onCancel} className="p-1 rounded hover:bg-muted/50 text-muted-foreground">
            <XIcon size={14} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-foreground/80">{description}</p>
          {children}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t bg-muted/20">
          <Button variant="outline" size="sm" onClick={onCancel}>
            {cancelLabel}
          </Button>
          <Button
            variant={isDestructive ? "destructive" : "default"}
            size="sm"
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    portalContainer ?? document.body,
  );
};

// Hook for easy usage
export function useConfirmDialog() {
  const [state, setState] = useState<{
    open: boolean;
    title: string;
    description: string;
    confirmLabel?: string;
    variant?: "default" | "destructive";
    resolve?: (confirmed: boolean) => void;
    children?: React.ReactNode;
  }>({ open: false, title: "", description: "" });

  const confirm = useCallback((opts: {
    title: string;
    description: string;
    confirmLabel?: string;
    variant?: "default" | "destructive";
    children?: React.ReactNode;
  }): Promise<boolean> => {
    return new Promise((resolve) => {
      setState({ ...opts, open: true, resolve });
    });
  }, []);

  const dialog = (
    <ConfirmDialog
      open={state.open}
      title={state.title}
      description={state.description}
      confirmLabel={state.confirmLabel}
      variant={state.variant}
      onConfirm={() => {
        state.resolve?.(true);
        setState((s) => ({ ...s, open: false }));
      }}
      onCancel={() => {
        state.resolve?.(false);
        setState((s) => ({ ...s, open: false }));
      }}
    >
      {state.children}
    </ConfirmDialog>
  );

  return { confirm, dialog };
}
