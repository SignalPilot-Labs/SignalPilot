import type {
  StandaloneChatBootstrap,
  StandaloneChatRun,
  getStandaloneChatProjectReadiness,
} from "~/lib/api";

type StandaloneChatProjectReadiness = Awaited<
  ReturnType<typeof getStandaloneChatProjectReadiness>
>;

/** Why the composer is blocked — surfaced under the input, never silent. */
export function composerDisabledReason(
  selectedProjectId: string | null,
  readiness: StandaloneChatProjectReadiness | undefined,
  currentRun: StandaloneChatRun | null,
): string | undefined {
  if (!selectedProjectId) return "Choose a project to start.";
  if (readiness?.ready === false && currentRun?.status !== "waiting_for_user") {
    return readiness?.message || "This project isn't ready for chat yet.";
  }
  if (currentRun?.status === "queued") return "Starting your last question…";
  if (currentRun?.status === "waiting_for_query_approval") {
    return "Approve or decline the proposed query above.";
  }
  return undefined;
}

/** The readiness notice copy and whether to offer the setup shortcut. */
export function readinessNotice(
  bootstrap: StandaloneChatBootstrap | undefined,
  readiness: StandaloneChatProjectReadiness | undefined,
): { message: string | null; showSetup: boolean } {
  const noProjects = bootstrap?.projects.length === 0;
  const message = noProjects
    ? bootstrap?.is_admin
      ? "No accessible project is ready. Set up a project and production connection to begin."
      : "No project is ready for data chat. Ask an administrator to finish setup."
    : readiness?.ready === false
      ? readiness.setup_cta
        ? `${readiness.message} Open project or connection settings to finish setup.`
        : readiness.message
      : null;
  const showSetup =
    bootstrap?.is_admin === true && (noProjects || readiness?.setup_cta === true);
  return { message, showSetup };
}

/** Outer shell classes: embedded fills its host; the page pins a min width
 * wide enough for whichever right-hand panel is open. */
export function chatShellClassName(
  embedded: boolean,
  settingsOpen: boolean,
  sidePanelOpen: boolean,
): string {
  if (embedded) return "h-full min-w-0 overflow-hidden";
  const minWidth = settingsOpen
    ? "min-w-[1180px]"
    : sidePanelOpen
      ? "min-w-[1360px]"
      : "min-w-[960px]";
  return `h-screen overflow-hidden p-4 ${minWidth}`;
}
