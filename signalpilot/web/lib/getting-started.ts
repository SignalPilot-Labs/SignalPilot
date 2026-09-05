export type GettingStartedJourney = "demo" | "setup" | "tour";
export type TourStep = 0 | 1 | 2 | 3 | 4 | 5;

export type SignalPilotGettingStarted = {
  version: 2;
  activeJourney: GettingStartedJourney | null;
  demo: { teamId?: string; replaySeen: boolean };
  setup: { teamId?: string; projectId?: string; invitationSkipped: boolean };
  tour: { status: "not_started" | "active" | "complete"; step: TourStep };
};

export const DEFAULT_GETTING_STARTED: SignalPilotGettingStarted = {
  version: 2,
  activeJourney: null,
  demo: { replaySeen: false },
  setup: { invitationSkipped: false },
  tour: { status: "not_started", step: 0 },
};

export const TOUR_STEPS = [
  { title: "Chat Agent", href: "/chats", target: "chat-composer" },
  { title: "Connections", href: "/connections", target: "connection-list" },
  { title: "Schema", href: "/schema", target: "schema-browser" },
  { title: "dbt lineage", href: "/lineage", target: "lineage-canvas" },
  { title: "Knowledge base", href: "/knowledge", target: "knowledge-area" },
  { title: "Team", href: "/settings/team", target: "team-members" },
] as const;

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

export function normalizeGettingStarted(value: unknown): SignalPilotGettingStarted {
  const root = record(value);
  const demo = record(root.demo);
  const setup = record(root.setup);
  const tour = record(root.tour);
  const journey = ["demo", "setup", "tour"].includes(String(root.activeJourney))
    ? root.activeJourney as GettingStartedJourney
    : null;
  const rawStep = Number(tour.step);
  const step = Math.max(0, Math.min(5, Number.isInteger(rawStep) ? rawStep : 0)) as TourStep;
  const status = ["not_started", "active", "complete"].includes(String(tour.status))
    ? tour.status as SignalPilotGettingStarted["tour"]["status"]
    : "not_started";
  return {
    version: 2,
    activeJourney: journey,
    demo: {
      ...(typeof demo.teamId === "string" ? { teamId: demo.teamId } : {}),
      replaySeen: demo.replaySeen === true,
    },
    setup: {
      ...(typeof setup.teamId === "string" ? { teamId: setup.teamId } : {}),
      ...(typeof setup.projectId === "string" ? { projectId: setup.projectId } : {}),
      invitationSkipped: setup.invitationSkipped === true,
    },
    tour: { status, step },
  };
}

export function canSelectStep(index: number, current: number): boolean {
  return index >= 0 && index <= current;
}

export function routeCompletesTourStep(pathname: string, step: TourStep): boolean {
  const expected = TOUR_STEPS[step].href;
  return pathname === expected || pathname.startsWith(`${expected}/`);
}

export function hiddenForSessionKey(sessionId: string): string {
  return `signalpilot:getting-started:hidden:${sessionId}`;
}

export function shouldShowGettingStarted(
  hidden: boolean,
  activeJourney: GettingStartedJourney | null,
  open: boolean,
): boolean {
  return !hidden && (activeJourney !== null || open);
}

export function deriveSetupStep(input: {
  teamMatches: boolean;
  hasProject: boolean;
  hasLinkedConnection: boolean;
  hasTeamKey: boolean;
  invitationSkipped: boolean;
  invitationCount: number;
  memberCount: number;
}): number {
  if (!input.teamMatches) return 0;
  if (!input.hasProject) return 1;
  if (!input.hasLinkedConnection) return 2;
  if (!input.hasTeamKey) return 3;
  if (!input.invitationSkipped && input.invitationCount === 0 && input.memberCount <= 1) return 4;
  return 5;
}

export const GETTING_STARTED_EVENT = "signalpilot:getting-started";
