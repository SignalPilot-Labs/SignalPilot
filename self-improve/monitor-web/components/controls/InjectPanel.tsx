"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/Button";

const PRESETS = [
  {
    label: "Wrap up",
    text: "You're done for now \u2014 commit your progress, write a summary of what you did and what remains, then stop.",
  },
  {
    label: "Focus security",
    text: "Focus specifically on security issues next. Check the SECURITY_AUDIT.md and address the CRITICAL and HIGH findings.",
  },
  {
    label: "Run tests",
    text: "Stop making changes and run the full test suite. Report any failures.",
  },
  {
    label: "Add tests",
    text: "Focus on adding test coverage for the gateway module. Don't make any other changes.",
  },
];

interface InjectPanelProps {
  open: boolean;
  onClose: () => void;
  onSend: (prompt: string) => void;
  busy: boolean;
}

export function InjectPanel({ open, onClose, onSend, busy }: InjectPanelProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => textareaRef.current?.focus(), 100);
    }
  }, [open]);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSend();
    }
    if (e.key === "Escape") {
      onClose();
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="overflow-hidden border-b border-[#1a1a1a]"
        >
          <div className="p-4 bg-[#0a0a0a]">
            {/* Presets */}
            <div className="flex gap-1.5 mb-3 flex-wrap">
              {PRESETS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => setText(p.text)}
                  className="text-[11px] sm:text-[9px] px-3 sm:px-2 py-2 sm:py-1 rounded bg-white/[0.03] text-[#777] hover:bg-white/[0.06] hover:text-[#aaa] transition-colors border border-[#1a1a1a]"
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a prompt to inject into the running agent..."
              rows={3}
              className="w-full bg-black/40 border border-[#1a1a1a] rounded px-3 py-2.5 text-[11px] text-[#ccc] placeholder-[#666] resize-y focus:outline-none focus:border-[#00ff88]/30 transition-all"
            />

            {/* Actions */}
            <div className="flex items-center justify-between mt-2.5">
              <span className="text-[9px] text-[#888]">
                {text.length > 0
                  ? `${text.length} chars`
                  : "Ctrl+Enter to send"}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  onClick={onClose}
                  icon={
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                    >
                      <line x1="2" y1="2" x2="8" y2="8" />
                      <line x1="8" y1="2" x2="2" y2="8" />
                    </svg>
                  }
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  size="md"
                  onClick={handleSend}
                  disabled={!text.trim() || busy}
                  icon={
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    >
                      <path d="M1 5h7M6 2l3 3-3 3" />
                    </svg>
                  }
                >
                  Send to Agent
                </Button>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
