import type { ConversationFileInfo, StandaloneChatEvent } from "~/lib/api";
import type { FixtureEvent } from "./chat-test-fixture-data";

/**
 * Fixture extension: the export files the scripted agent writes late in the
 * run — an HTML report, an SVG chart, a CSV, and a markdown summary — so
 * every inline artifact card variant is exercisable on /chats/test.
 *
 * chat-test-fixture-data.ts splices `artifactFileEvents()` into its event
 * script (only a type flows the other way, so there is no import cycle);
 * chat-test-fixture.ts appends `fixtureArtifactFiles()` to the simulated
 * manifest. A file's manifest row appears only once its `files_changed`
 * event has landed, which opens a deliberate pending window between the
 * Write tool call and the mirror confirmation (12.1s → 13.0s for the
 * report) that the card UI renders as "Still being written".
 */

export const FIXTURE_REPORT_FILE_PATH = "exports/q3_regional_review.html";
export const FIXTURE_CHART_IMAGE_PATH = "exports/q3_growth_by_region.svg";
export const FIXTURE_CSV_FILE_PATH = "exports/q3_revenue_by_region.csv";
export const FIXTURE_SUMMARY_FILE_PATH = "exports/q3_summary.md";

export const REPORT_HTML_FILE = `<!doctype html><html><head><title>Q3 regional review</title></head>
<body><h1>Q3 2025 Regional Revenue Review</h1>
<p>Q3 revenue reached $16.1M, up 10.4% quarter over quarter. EMEA drove
the absolute growth; APAC grew fastest from a smaller base.</p>
<table><tr><th>Region</th><th>Q2</th><th>Q3</th><th>Growth</th></tr>
<tr><td>AMER</td><td>$8.93M</td><td>$9.20M</td><td>+3.1%</td></tr>
<tr><td>EMEA</td><td>$4.10M</td><td>$4.81M</td><td>+17.3%</td></tr>
<tr><td>APAC</td><td>$1.61M</td><td>$2.12M</td><td>+31.5%</td></tr></table>
</body></html>`;

export const CHART_SVG_FILE = `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="240" viewBox="0 0 480 240">
<rect width="480" height="240" fill="#ffffff"/>
<rect x="60" y="40" width="80" height="160" fill="#4c78a8"/>
<rect x="200" y="90" width="80" height="110" fill="#f58518"/>
<rect x="340" y="150" width="80" height="50" fill="#54a24b"/>
<text x="100" y="225" text-anchor="middle" font-size="12">AMER</text>
<text x="240" y="225" text-anchor="middle" font-size="12">EMEA</text>
<text x="380" y="225" text-anchor="middle" font-size="12">APAC</text>
</svg>`;

export const CSV_FILE = `region,revenue_q3,revenue_q2,growth_pct
AMER,9204100,8930600,3.1
EMEA,4812400,4101900,17.3
APAC,2118800,1611200,31.5
`;

export const SUMMARY_MD_FILE = `# Q3 regional summary

- Total Q3 revenue: **$16.1M** (+10.4% QoQ)
- EMEA drove absolute growth (+17.3% to $4.81M)
- APAC grew fastest from a small base (+31.5% to $2.12M)
- AMER stayed steady (+3.1% to $9.20M, 57% of total)
`;

/** Millisecond offsets shared by the events and the simulated manifest. */
const REPORT_WRITE_AT = 12_100;
const REPORT_MIRRORED_AT = 13_000;
const CHART_MIRRORED_AT = 13_600;
const CSV_MIRRORED_AT = 14_050;
const SUMMARY_WRITE_AT = 15_150;
const SUMMARY_MIRRORED_AT = 15_460;

/** The export-file segment of the scripted run: three Write chains, each
 * mirrored by a content-free files_changed event. Slots between the Bash
 * check (11.9s) and the Edit (14.3s). */
export function artifactFileEvents(runId: string): FixtureEvent[] {
  return [
    {
      at: REPORT_WRITE_AT,
      run_id: runId,
      sequence: 0,
      type: "tool_started",
      payload: {
        tool: "Write",
        input: { file_path: FIXTURE_REPORT_FILE_PATH, content: REPORT_HTML_FILE },
      },
    },
    {
      at: 12_800,
      run_id: runId,
      sequence: 0,
      type: "tool_completed",
      payload: { tool_call_id: "t8a", summary: "The tool completed.", error: false },
    },
    {
      at: REPORT_MIRRORED_AT,
      run_id: runId,
      sequence: 0,
      type: "files_changed",
      payload: { changed: [FIXTURE_REPORT_FILE_PATH], deleted: [] },
    },
    {
      at: 13_050,
      run_id: runId,
      sequence: 0,
      type: "tool_started",
      payload: {
        tool: "Write",
        input: { file_path: FIXTURE_CHART_IMAGE_PATH, content: CHART_SVG_FILE },
      },
    },
    {
      at: 13_450,
      run_id: runId,
      sequence: 0,
      type: "tool_completed",
      payload: { tool_call_id: "t8b", summary: "The tool completed.", error: false },
    },
    {
      at: CHART_MIRRORED_AT,
      run_id: runId,
      sequence: 0,
      type: "files_changed",
      payload: { changed: [FIXTURE_CHART_IMAGE_PATH], deleted: [] },
    },
    {
      at: 13_700,
      run_id: runId,
      sequence: 0,
      type: "tool_started",
      payload: {
        tool: "Write",
        input: { file_path: FIXTURE_CSV_FILE_PATH, content: CSV_FILE },
      },
    },
    {
      at: 13_950,
      run_id: runId,
      sequence: 0,
      type: "tool_completed",
      payload: { tool_call_id: "t8c", summary: "The tool completed.", error: false },
    },
    {
      at: CSV_MIRRORED_AT,
      run_id: runId,
      sequence: 0,
      type: "files_changed",
      payload: { changed: [FIXTURE_CSV_FILE_PATH], deleted: [] },
    },
  ];
}

/** A fifth file (markdown summary) written after the Edit chain, so the
 * ≥2-overflow collapse rule is exercisable mid-run: five cards at ~15.5s
 * render as three full cards plus two compact rows. Slots between the Edit
 * completion (15.1s) and the closing TodoWrite (15.5s). */
export function lateArtifactFileEvents(runId: string): FixtureEvent[] {
  return [
    {
      at: SUMMARY_WRITE_AT,
      run_id: runId,
      sequence: 0,
      type: "tool_started",
      payload: {
        tool: "Write",
        input: { file_path: FIXTURE_SUMMARY_FILE_PATH, content: SUMMARY_MD_FILE },
      },
    },
    {
      at: 15_380,
      run_id: runId,
      sequence: 0,
      type: "tool_completed",
      payload: { tool_call_id: "t8d", summary: "The tool completed.", error: false },
    },
    {
      at: SUMMARY_MIRRORED_AT,
      run_id: runId,
      sequence: 0,
      type: "files_changed",
      payload: { changed: [FIXTURE_SUMMARY_FILE_PATH], deleted: [] },
    },
  ];
}

function mirrored(events: StandaloneChatEvent[], path: string): boolean {
  return events.some(
    (event) =>
      event.type === "files_changed" &&
      Array.isArray(event.payload.changed) &&
      (event.payload.changed as unknown[]).includes(path),
  );
}

/**
 * The manifest rows for the export files, gated on their files_changed
 * events so the pending → ready transition replays deterministically.
 * `runId` and `createdAt` come from chat-test-fixture.ts.
 */
export function fixtureArtifactFiles(
  events: StandaloneChatEvent[],
  runId: string,
  createdAt: (atMs: number) => string,
): ConversationFileInfo[] {
  const entries: Array<{
    id: string;
    path: string;
    kind: ConversationFileInfo["kind"];
    mime: string;
    size: number;
    at: number;
  }> = [
    {
      id: "file-fixture-report",
      path: FIXTURE_REPORT_FILE_PATH,
      kind: "html",
      mime: "text/html",
      size: REPORT_HTML_FILE.length,
      at: REPORT_MIRRORED_AT,
    },
    {
      id: "file-fixture-chart",
      path: FIXTURE_CHART_IMAGE_PATH,
      kind: "image",
      mime: "image/svg+xml",
      size: CHART_SVG_FILE.length,
      at: CHART_MIRRORED_AT,
    },
    {
      id: "file-fixture-csv",
      path: FIXTURE_CSV_FILE_PATH,
      kind: "data",
      mime: "text/csv",
      size: CSV_FILE.length,
      at: CSV_MIRRORED_AT,
    },
    {
      id: "file-fixture-summary",
      path: FIXTURE_SUMMARY_FILE_PATH,
      kind: "markdown",
      mime: "text/markdown",
      size: SUMMARY_MD_FILE.length,
      at: SUMMARY_MIRRORED_AT,
    },
  ];
  return entries
    .filter((entry) => mirrored(events, entry.path))
    .map((entry) => ({
      id: entry.id,
      path: entry.path,
      filename: entry.path.split("/").pop() ?? entry.path,
      kind: entry.kind,
      mime_type: entry.mime,
      byte_size: entry.size,
      content_hash: `${entry.id}-hash-1`,
      origin_run_id: runId,
      origin: "mirror",
      status: "active",
      created_at: createdAt(entry.at),
      updated_at: createdAt(entry.at),
    }));
}
