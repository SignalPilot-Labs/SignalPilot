import { useState } from "react";
import styles from "./MiniCopyBlock.module.css";

export default function MiniCopyBlock({
  label,
  code,
  plain,
}: {
  label: string;
  code: string;
  plain?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {}
  }

  const lines = code.split("\n");

  return (
    <div className={styles.block}>
      <div className={styles.header}>
        <span className={styles.label}>{label}</span>
        <button
          onClick={copy}
          className={styles.copyBtn}
          aria-label={`Copy ${label}`}
        >
          {copied ? "copied" : "copy"}
        </button>
      </div>
      <pre className={styles.pre}>
        {lines.map((line, i) => {
          if (plain) {
            return <div key={i}>{line}</div>;
          }

          const isComment = line.trimStart().startsWith("#");
          const isContinuation =
            i > 0 && lines[i - 1].trimEnd().endsWith("\\");
          const isEmpty = line.trim() === "";
          const showPrompt = !isComment && !isContinuation && !isEmpty;

          return (
            <div key={i} className={isEmpty ? styles.emptyLine : undefined}>
              {showPrompt && <span className={styles.prompt}>$ </span>}
              <span className={isComment ? styles.comment : undefined}>
                {line}
              </span>
            </div>
          );
        })}
      </pre>
    </div>
  );
}
