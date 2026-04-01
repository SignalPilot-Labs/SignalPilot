"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/Button";
import {
  PaperAirplaneIcon,
  XMarkIcon,
} from "@heroicons/react/16/solid";

const PRESETS = [
  { label: "Wrap up", text: "You're done for now \u2014 commit your progress, write a summary of what you did and what remains, then stop." },
  { label: "Focus security", text: "Focus specifically on security issues next. Check the SECURITY_AUDIT.md and address the CRITICAL and HIGH findings." },
  { label: "Run tests", text: "Stop making changes and run the full test suite. Report any failures." },
  { label: "Add tests", text: "Focus on adding test coverage for the gateway module. Don't make any other changes." },
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
          className="overflow-hidden border-b border-white/[0.06]"
        >
          <div className="p-4 bg-[#0c0f14]">
            {/* Presets */}
            <div className="flex gap-1.5 mb-3 flex-wrap">
              {PRESETS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => setText(p.text)}
                  className="text-[10px] px-2.5 py-1 rounded-full bg-white/[0.04] text-zinc-400 hover:bg-white/[0.08] hover:text-zinc-300 transition-colors border border-white/[0.04]"
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
              className="w-full bg-black/30 border border-white/[0.06] rounded-lg px-3 py-2.5 text-[12px] text-zinc-300 placeholder-zinc-600 resize-y focus:outline-none focus:border-sky-500/40 focus:ring-1 focus:ring-sky-500/20 transition-all"
            />

            {/* Actions */}
            <div className="flex items-center justify-between mt-2.5">
              <span className="text-[10px] text-zinc-600">
                {text.length > 0 ? `${text.length} chars` : "Ctrl+Enter to send"}
              </span>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={onClose} icon={<XMarkIcon className="h-3 w-3" />}>
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  size="md"
                  onClick={handleSend}
                  disabled={!text.trim() || busy}
                  icon={<PaperAirplaneIcon className="h-3 w-3" />}
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
