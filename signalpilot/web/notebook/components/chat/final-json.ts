export interface FinalJsonSummary {
  summary: string;
  confidenceScore: number | null;
  finalAnswer: string;
  gotchas: string[];
  analysisMethod: string;
  notionComment: string;
  notionCharts: Array<{ title?: string; url?: string }>;
  prettyJson: string;
}

function extractBalancedJsonObjects(content: string): string[] {
  const candidates: string[] = [];
  let start = -1;
  let depth = 0;
  let inString = false;
  let escaped = false;

  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];

    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }

    if (char === '"') {
      inString = true;
      continue;
    }

    if (char === "{") {
      if (depth === 0) {start = index;}
      depth += 1;
      continue;
    }

    if (char === "}" && depth > 0) {
      depth -= 1;
      if (depth === 0 && start !== -1) {
        candidates.push(content.slice(start, index + 1));
        start = -1;
      }
    }
  }

  return candidates;
}

function extractJsonCandidates(content: string): string[] {
  const trimmed = content.trim();
  const candidates = [trimmed];
  const fencedRegex = /```(?:json)?\s*([\s\S]*?)\s*```/gi;
  let fencedMatch: RegExpExecArray | null;

  while ((fencedMatch = fencedRegex.exec(trimmed))) {
    candidates.push(fencedMatch[1].trim());
  }

  candidates.push(...extractBalancedJsonObjects(trimmed).reverse());

  return candidates.filter(Boolean);
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {return [];}
  return value.map((item) => String(item));
}

function chartArray(value: unknown): Array<{ title?: string; url?: string }> {
  if (!Array.isArray(value)) {return [];}
  return value
    .filter((item): item is Record<string, unknown> => {
      return typeof item === "object" && item !== null;
    })
    .map((item) => ({
      title: typeof item.title === "string" ? item.title : undefined,
      url: typeof item.url === "string" ? item.url : undefined,
    }));
}

export function parseFinalJsonSummary(
  content: string,
): FinalJsonSummary | null {
  for (const candidate of extractJsonCandidates(content)) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(candidate);
    } catch {
      continue;
    }

    if (
      typeof parsed === "object" &&
      parsed !== null &&
      !Array.isArray(parsed) &&
      typeof (parsed as Record<string, unknown>).content === "string"
    ) {
      const nested = parseFinalJsonSummary(
        (parsed as Record<string, unknown>).content as string,
      );
      if (nested) {return nested;}
    }

    const summary = summarizeParsedFinalJson(parsed);
    if (summary) {return summary;}
  }

  return null;
}

function summarizeParsedFinalJson(parsed: unknown): FinalJsonSummary | null {
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return null;
  }

  const object = parsed as Record<string, unknown>;
  const hasFinalShape =
    "summary" in object &&
    ("confidenceScore" in object || "confidence_score" in object) &&
    ("finalAnswer" in object || "final_answer" in object) &&
    ("notionComment" in object || "notion_comment" in object);
  if (!hasFinalShape) {return null;}

  const confidence = object.confidenceScore ?? object.confidence_score;
  return {
    summary: String(object.summary ?? ""),
    confidenceScore:
      typeof confidence === "number" && Number.isFinite(confidence)
        ? confidence
        : null,
    finalAnswer: String(object.finalAnswer ?? object.final_answer ?? ""),
    gotchas: stringArray(object.gotchas),
    analysisMethod: String(
      object.analysisMethod ?? object.analysis_method ?? "",
    ),
    notionComment: String(object.notionComment ?? object.notion_comment ?? ""),
    notionCharts: chartArray(object.notionCharts ?? object.notion_charts),
    prettyJson: JSON.stringify(object, null, 2),
  };
}
