"use client";

/**
 * Lightweight SQL syntax highlighter — no dependencies.
 * Tokenizes SQL and applies terminal-aesthetic colors.
 */

const SQL_KEYWORDS = new Set([
  "select",
  "from",
  "where",
  "and",
  "or",
  "not",
  "in",
  "is",
  "null",
  "as",
  "join",
  "left",
  "right",
  "inner",
  "outer",
  "cross",
  "on",
  "group",
  "by",
  "order",
  "having",
  "limit",
  "offset",
  "union",
  "all",
  "distinct",
  "case",
  "when",
  "then",
  "else",
  "end",
  "insert",
  "into",
  "values",
  "update",
  "set",
  "delete",
  "create",
  "alter",
  "drop",
  "table",
  "index",
  "view",
  "exists",
  "between",
  "like",
  "ilike",
  "asc",
  "desc",
  "count",
  "sum",
  "avg",
  "min",
  "max",
  "with",
  "recursive",
  "true",
  "false",
  "cast",
  "coalesce",
  "nullif",
  "extract",
  "interval",
  "over",
  "partition",
  "row_number",
  "rank",
]);

const SQL_FUNCTIONS = new Set([
  "count",
  "sum",
  "avg",
  "min",
  "max",
  "coalesce",
  "nullif",
  "cast",
  "extract",
  "row_number",
  "rank",
  "dense_rank",
  "lag",
  "lead",
  "first_value",
  "last_value",
  "now",
  "current_timestamp",
  "current_date",
  "length",
  "lower",
  "upper",
  "trim",
  "substring",
  "replace",
  "concat",
  "abs",
  "round",
  "floor",
  "ceil",
  "array_agg",
  "string_agg",
  "json_agg",
]);

interface Token {
  type:
    | "keyword"
    | "function"
    | "string"
    | "number"
    | "comment"
    | "operator"
    | "identifier";
  value: string;
}

function tokenize(sql: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;

  while (i < sql.length) {
    // Whitespace — pass through as identifier
    if (/\s/.test(sql[i])) {
      let start = i;
      while (i < sql.length && /\s/.test(sql[i])) i++;
      tokens.push({ type: "identifier", value: sql.slice(start, i) });
      continue;
    }

    // Single-line comment
    if (sql[i] === "-" && sql[i + 1] === "-") {
      let start = i;
      while (i < sql.length && sql[i] !== "\n") i++;
      tokens.push({ type: "comment", value: sql.slice(start, i) });
      continue;
    }

    // String literal
    if (sql[i] === "'") {
      let start = i;
      i++;
      while (i < sql.length && sql[i] !== "'") {
        if (sql[i] === "'" && sql[i + 1] === "'") i++; // escaped quote
        i++;
      }
      if (i < sql.length) i++; // closing quote
      tokens.push({ type: "string", value: sql.slice(start, i) });
      continue;
    }

    // Number
    if (/\d/.test(sql[i])) {
      let start = i;
      while (i < sql.length && /[\d.]/.test(sql[i])) i++;
      tokens.push({ type: "number", value: sql.slice(start, i) });
      continue;
    }

    // Operators
    if (/[=<>!+\-*/%,;().]/.test(sql[i])) {
      tokens.push({ type: "operator", value: sql[i] });
      i++;
      continue;
    }

    // Word (keyword / function / identifier)
    if (/[a-zA-Z_]/.test(sql[i])) {
      let start = i;
      while (i < sql.length && /[a-zA-Z0-9_]/.test(sql[i])) i++;
      const word = sql.slice(start, i);
      const lower = word.toLowerCase();

      if (SQL_KEYWORDS.has(lower)) {
        tokens.push({ type: "keyword", value: word });
      } else if (SQL_FUNCTIONS.has(lower)) {
        tokens.push({ type: "function", value: word });
      } else {
        tokens.push({ type: "identifier", value: word });
      }
      continue;
    }

    // Fallback
    tokens.push({ type: "identifier", value: sql[i] });
    i++;
  }

  return tokens;
}

const TOKEN_COLORS: Record<Token["type"], string> = {
  keyword: "text-blue-400",
  function: "text-cyan-400",
  string: "text-green-400",
  number: "text-[var(--color-warning)]",
  comment: "text-[var(--color-text-dim)] italic",
  operator: "text-[var(--color-text-dim)]",
  identifier: "text-[var(--color-text-muted)]",
};

export function SqlHighlight({
  sql,
  className = "",
}: {
  sql: string;
  className?: string;
}) {
  const tokens = tokenize(sql);

  return (
    <code className={`whitespace-pre-wrap ${className}`}>
      {tokens.map((token, i) => (
        <span key={i} className={TOKEN_COLORS[token.type]}>
          {token.value}
        </span>
      ))}
    </code>
  );
}
