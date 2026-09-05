"use client";

import { useOrganization, useOrganizationList, useSession, useUser } from "@clerk/nextjs";
import { Check, ChevronRight, Loader2, Map, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GitHubImportForm } from "~/components/projects/projects-overview-page";
import { SetupConnectionForm } from "~/components/getting-started/setup-connection-form";
import { AnthropicKeyForm } from "~/components/integrations/anthropic-key-form";
import { TeamInvitationForm } from "~/components/team/team-invitations-section";
import { ROLE_ADMIN } from "~/lib/team/roles";
import type { OrganizationResource } from "@clerk/types";
import {
  bootstrapDemo,
  getDemoBootstrap,
  getConnections,
  getOrgSecrets,
  getStandaloneChatProjectReadiness,
  getWorkspaceProjects,
  setDefaultStandaloneChatProject,
  updateWorkspaceProject,
} from "~/lib/api";
import type { DemoBootstrapResponse, WorkspaceProjectInfo } from "~/lib/types";
import {
  DEFAULT_GETTING_STARTED,
  GETTING_STARTED_EVENT,
  TOUR_STEPS,
  canSelectStep,
  deriveSetupStep,
  hiddenForSessionKey,
  normalizeGettingStarted,
  routeCompletesTourStep,
  shouldShowGettingStarted,
  type GettingStartedJourney,
  type SignalPilotGettingStarted,
  type TourStep,
} from "~/lib/getting-started";

type ControllerEvent = CustomEvent<{ journey?: GettingStartedJourney | null; expanded?: boolean }>;

const SETUP_STEPS = ["Create your Team", "Import your dbt project", "Connect your warehouse", "Add your Anthropic key", "Invite a technical teammate", "Ready"];
const DEMO_PHASES = ["Creating your demo team", "Preparing your private demo data", "Loading the demo project", "Opening SignalPilot"];

export function GettingStartedRoot() {
  const router = useRouter();
  const pathname = usePathname();
  const { user } = useUser();
  const { session } = useSession();
  const { organization, invitations, memberships } = useOrganization({
    invitations: { pageSize: 20, keepPreviousData: true },
    memberships: { pageSize: 20, keepPreviousData: true },
  });
  const { createOrganization, setActive, userMemberships } = useOrganizationList({
    userMemberships: { infinite: true, pageSize: 50 },
  });
  const [state, setState] = useState<SignalPilotGettingStarted>(DEFAULT_GETTING_STARTED);
  const [open, setOpen] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState<DemoBootstrapResponse | null>(null);
  const [teamName, setTeamName] = useState("");
  const [setupProject, setSetupProject] = useState<WorkspaceProjectInfo | null>(null);
  const [hasTeamKey, setHasTeamKey] = useState(false);
  const [ready, setReady] = useState(false);
  const [spotlight, setSpotlight] = useState<DOMRect | null>(null);
  const [selectedTourStep, setSelectedTourStep] = useState<TourStep>(0);
  const [selectedSetupStep, setSelectedSetupStep] = useState(0);
  const compactRef = useRef<HTMLButtonElement>(null);
  const demoBusyRef = useRef(false);
  const metadataHydratedRef = useRef(false);

  useEffect(() => {
    if (!user || metadataHydratedRef.current) return;
    metadataHydratedRef.current = true;
    const normalized = normalizeGettingStarted(user.unsafeMetadata.signalpilotGettingStarted);
    setState(normalized);
    if (normalized.activeJourney === "tour") setSelectedTourStep(normalized.tour.step);
  }, [user]);

  useEffect(() => {
    if (state.activeJourney === "demo" || state.activeJourney === "setup") setOpen(true);
  }, [state.activeJourney]);

  const persist = useCallback(async (next: SignalPilotGettingStarted, completeEntry = false) => {
    setState(next);
    if (!user) return;
    await user.update({ unsafeMetadata: {
      ...user.unsafeMetadata,
      ...(completeEntry ? { onboardingCompleted: true } : {}),
      signalpilotGettingStarted: next,
    } });
  }, [user]);

  useEffect(() => {
    if (!session?.id) return;
    setHidden(sessionStorage.getItem(hiddenForSessionKey(session.id)) === "1");
  }, [session?.id]);

  useEffect(() => {
    const handler = (raw: Event) => {
      const event = raw as ControllerEvent;
      setHidden(false);
      setOpen(event.detail?.expanded ?? true);
      if (event.detail?.journey !== undefined) {
        const journey = event.detail.journey;
        if (journey === "tour") setSelectedTourStep(state.tour.status === "active" ? state.tour.step : 0);
        void persist({
          ...state,
          activeJourney: journey,
          ...(journey === "tour" && state.tour.status !== "active"
            ? { tour: { status: "active" as const, step: 0 as TourStep } }
            : {}),
        });
      }
    };
    window.addEventListener(GETTING_STARTED_EVENT, handler);
    return () => window.removeEventListener(GETTING_STARTED_EVENT, handler);
  }, [persist, state]);

  useEffect(() => {
    const returnTo = sessionStorage.getItem("signalpilot:getting-started:oauth-return");
    if (!returnTo || !window.location.search.includes("installed=true")) return;
    sessionStorage.removeItem("signalpilot:getting-started:oauth-return");
    setOpen(true);
    router.replace(returnTo);
  }, [router]);

  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      requestAnimationFrame(() => compactRef.current?.focus());
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [open]);

  const switchToTeam = useCallback(async (teamId: string, destination: string) => {
    if (organization?.id === teamId) return true;
    const member = userMemberships.data?.some((membership) => membership.organization.id === teamId);
    if (!member || !setActive) return false;
    await setActive({ organization: teamId });
    window.location.href = destination;
    return false;
  }, [organization?.id, setActive, userMemberships.data]);

  useEffect(() => {
    if (state.activeJourney !== "setup" || !state.setup.teamId || organization?.id === state.setup.teamId) return;
    void switchToTeam(state.setup.teamId, "/dashboard");
  }, [organization?.id, state.activeJourney, state.setup.teamId, switchToTeam]);

  const startDemo = useCallback(async () => {
    if (!user || !createOrganization || !setActive || userMemberships.isLoading || demoBusyRef.current) return;
    demoBusyRef.current = true;
    setBusy(true); setError(null); setOpen(true);
    try {
      if (state.activeJourney !== "demo") await persist({ ...state, activeJourney: "demo" });
      let teamId = state.demo.teamId;
      if (teamId && !userMemberships.data?.some((membership) => membership.organization.id === teamId)) {
        teamId = undefined;
      }
      if (teamId && !(await switchToTeam(teamId, "/onboarding?journey=demo"))) return;
      if (!teamId) {
        const email = user.primaryEmailAddress?.emailAddress || "My";
        const demoTeamName = `${email}'s Demo Team`;
        const existingMembership = userMemberships.data?.find(
          (membership) => membership.organization.name === demoTeamName,
        );
        teamId = existingMembership?.organization.id;
        if (!teamId) {
          const org = await createOrganization({ name: demoTeamName });
          teamId = org.id;
        }
        const next = { ...state, activeJourney: "demo" as const, demo: { ...state.demo, teamId } };
        await persist(next, true);
        await setActive({ organization: teamId });
        window.location.href = "/onboarding?journey=demo";
        return;
      }
      const result = await bootstrapDemo();
      setDemo(result);
    } catch {
      setError("We couldn't prepare the demo. Try again.");
    } finally { demoBusyRef.current = false; setBusy(false); }
  }, [createOrganization, persist, setActive, state, switchToTeam, user, userMemberships.data, userMemberships.isLoading]);

  useEffect(() => {
    if (state.activeJourney !== "demo" || busy) return;
    if (!state.demo.teamId) { void startDemo(); return; }
    if (organization?.id !== state.demo.teamId) return;
    if (!demo) void startDemo();
  }, [busy, demo, organization?.id, startDemo, state.activeJourney, state.demo.teamId]);

  useEffect(() => {
    if (state.activeJourney !== "demo" || demo?.status !== "provisioning") return;
    const timer = window.setInterval(() => {
      void getDemoBootstrap().then((next) => {
        setDemo(next);
        if (next.status === "ready" && next.conversation_id && next.replay_run_id) {
          void persist({ ...state, demo: { ...state.demo, replaySeen: true } });
          router.push(`/chats/${next.conversation_id}?replay=${next.replay_run_id}`);
        }
      }).catch(() => setError("We couldn't prepare the demo. Try again."));
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [demo?.status, persist, router, state]);

  useEffect(() => {
    if (demo?.status === "ready" && demo.conversation_id && demo.replay_run_id && pathname === "/onboarding") {
      void persist({ ...state, demo: { ...state.demo, replaySeen: true } });
      router.push(`/chats/${demo.conversation_id}?replay=${demo.replay_run_id}`);
    }
  }, [demo, pathname, persist, router, state]);

  const startSetup = useCallback(async () => {
    setOpen(true); setError(null);
    const teamId = state.setup.teamId && userMemberships.data?.some(
      (membership) => membership.organization.id === state.setup.teamId,
    ) ? state.setup.teamId : undefined;
    if (teamId) {
      if (state.activeJourney !== "setup") await persist({ ...state, activeJourney: "setup" });
      if (!(await switchToTeam(teamId, "/dashboard"))) return;
    }
    if (!teamId && organization) {
      try {
        const connections = await getConnections();
        if (!connections.some((connection) => connection.tags?.includes("sp-demo"))) {
          await persist({
            ...state,
            activeJourney: "setup",
            setup: { ...state.setup, teamId: organization.id },
          }, true);
          return;
        }
      } catch { /* keep the dedicated-Team creation path available */ }
    }
    await persist({ ...state, activeJourney: "setup" });
  }, [organization, persist, state, switchToTeam, userMemberships.data]);

  async function createSetupTeam() {
    if (!teamName.trim() || !createOrganization || !setActive) return;
    setBusy(true); setError(null);
    try {
      const org = await createOrganization({ name: teamName.trim() });
      const next = { ...state, activeJourney: "setup" as const, setup: { ...state.setup, teamId: org.id } };
      await persist(next, true);
      await setActive({ organization: org.id });
      window.location.href = "/dashboard";
    } catch (reason) { setError(String(reason)); setBusy(false); }
  }

  const refreshSetup = useCallback(async () => {
    if (state.activeJourney !== "setup" || !organization) return;
    try {
      const projects = await getWorkspaceProjects("active");
      const project = projects.projects.find((item) =>
        (item.tags || []).includes("sp-onboarding") &&
        (item.tags || []).includes("journey:setup-v2"),
      ) || null;
      setSetupProject(project);
      if (project && state.setup.projectId !== project.id) {
        void persist({ ...state, setup: { ...state.setup, projectId: project.id, teamId: organization.id } });
      }
      const [secret, readiness] = await Promise.all([
        getOrgSecrets(),
        project ? getStandaloneChatProjectReadiness(project.id).catch(() => null) : Promise.resolve(null),
      ]);
      setHasTeamKey(secret.has_key);
      setReady(Boolean(readiness?.ready && secret.has_key));
    } catch { /* incomplete setup remains actionable */ }
  }, [organization, persist, state]);

  useEffect(() => { void refreshSetup(); }, [refreshSetup]);
  useEffect(() => {
    if (state.activeJourney !== "setup" || !setupProject || ready) return;
    const timer = window.setInterval(() => { void refreshSetup(); }, 5_000);
    return () => window.clearInterval(timer);
  }, [ready, refreshSetup, setupProject, state.activeJourney]);

  async function startTour() {
    const next = { ...state, activeJourney: "tour" as const, tour: { status: "active" as const, step: 0 as TourStep } };
    await persist(next);
    setSelectedTourStep(0);
    setOpen(false);
    router.push(TOUR_STEPS[0].href);
  }

  async function handleSetupProjectImported(project?: WorkspaceProjectInfo) {
    if (!project) return;
    const tagged = await updateWorkspaceProject(project.id, {
      tags: Array.from(new Set([...(project.tags || []), "sp-onboarding", "journey:setup-v2"])),
    });
    setSetupProject(tagged);
    await persist({
      ...state,
      setup: { ...state.setup, projectId: tagged.id, teamId: organization?.id },
    });
  }

  const tourStep = state.tour.step;
  useEffect(() => {
    if (state.activeJourney !== "tour" || !routeCompletesTourStep(pathname, selectedTourStep)) return;
    if (selectedTourStep === 5) {
      if (state.tour.status !== "complete") void persist({ ...state, tour: { status: "complete", step: 5 } });
      return;
    }
    if (selectedTourStep >= tourStep) {
      const unlocked = (selectedTourStep + 1) as TourStep;
      void persist({ ...state, tour: { status: "active", step: unlocked } });
    }
  }, [pathname, persist, selectedTourStep, state, tourStep]);
  useEffect(() => {
    if (state.activeJourney !== "tour" || hidden) { setSpotlight(null); return; }
    const update = () => {
      const target = document.querySelector(`[data-tour-id="${TOUR_STEPS[selectedTourStep].target}"]`);
      setSpotlight(target?.getBoundingClientRect() ?? null);
    };
    const frame = requestAnimationFrame(update);
    const observer = new MutationObserver(update);
    observer.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [hidden, pathname, selectedTourStep, state.activeJourney]);

  async function nextTourStep() {
    const current = TOUR_STEPS[selectedTourStep];
    if (!routeCompletesTourStep(pathname, selectedTourStep)) { router.push(current.href); return; }
    if (selectedTourStep === 5) {
      await persist({ ...state, activeJourney: null, tour: { status: "complete", step: 5 } });
      setOpen(false); setSpotlight(null); return;
    }
    const nextStep = (selectedTourStep + 1) as TourStep;
    setSelectedTourStep(nextStep);
    if (nextStep > tourStep) await persist({ ...state, tour: { status: "active", step: nextStep } });
    router.push(TOUR_STEPS[nextStep].href);
  }

  const setupStep = useMemo(() => {
    return deriveSetupStep({
      teamMatches: Boolean(state.setup.teamId && organization?.id === state.setup.teamId),
      hasProject: Boolean(setupProject),
      hasLinkedConnection: Boolean(setupProject?.connection_name),
      hasTeamKey,
      invitationSkipped: state.setup.invitationSkipped,
      invitationCount: invitations?.data?.length || 0,
      memberCount: memberships?.data?.length || 0,
    });
  }, [hasTeamKey, invitations?.data?.length, memberships?.data?.length, organization?.id, setupProject, state.setup]);
  useEffect(() => { setSelectedSetupStep(setupStep); }, [setupStep]);

  if (!user || !shouldShowGettingStarted(hidden, state.activeJourney, open)) return null;
  const journeyTitle = state.activeJourney === "demo" ? "Explore a demo" : state.activeJourney === "setup" ? "Connect your data" : state.activeJourney === "tour" ? "Product Tour" : "Getting Started";
  const currentTask = state.activeJourney === "setup" ? SETUP_STEPS[selectedSetupStep] : state.activeJourney === "tour" ? TOUR_STEPS[selectedTourStep].title : state.activeJourney === "demo" ? DEMO_PHASES[demo?.phase === "project" ? 2 : demo?.phase === "opening" ? 3 : state.demo.teamId ? 1 : 0] : "Choose a path";
  const progress = state.activeJourney === "setup" ? setupStep : state.activeJourney === "tour" ? tourStep : demo?.status === "ready" ? 4 : state.demo.teamId ? 1 : 0;
  const total = state.activeJourney === "demo" ? 4 : 6;
  const left = pathname === "/onboarding" ? "1rem" : "calc(14rem + 1rem)";

  return (
    <>
      {spotlight && state.activeJourney === "tour" && (
        <div aria-hidden="true" className="pointer-events-none fixed z-[69] rounded-xl border-2 border-[var(--color-success)] shadow-[0_0_0_6px_rgba(52,211,153,0.12)]" style={{ left: spotlight.left - 6, top: spotlight.top - 6, width: spotlight.width + 12, height: spotlight.height + 12 }} />
      )}
      {!open ? (
        <button ref={compactRef} type="button" onClick={() => setOpen(true)} className="fixed bottom-4 z-[70] w-72 border border-[var(--color-border)] bg-[var(--color-bg-card)] p-3 text-left shadow-2xl" style={{ left }}>
          <span className="block text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-dim)]">{journeyTitle}</span>
          <span className="mt-1 flex items-center gap-2 text-xs text-[var(--color-text)]"><span className="truncate">{currentTask}</span><ChevronRight className="ml-auto h-3 w-3" /></span>
          <span className="mt-2 block h-1 bg-[var(--color-border)]"><span className="block h-full bg-[var(--color-success)]" style={{ width: `${((progress + 1) / total) * 100}%` }} /></span>
        </button>
      ) : (
        <aside aria-label="Getting Started" className="fixed bottom-4 z-[70] flex w-[544px] max-h-[calc(100vh-32px)] flex-col overflow-hidden border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-2xl" style={{ left }}>
          <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-bg-card)] px-5 py-4">
            <Map className="h-4 w-4 text-[var(--color-success)]" /><div className="min-w-0 flex-1"><p className="text-[10px] uppercase tracking-[0.12em] text-[var(--color-text-dim)]">Getting Started</p><h2 className="text-sm font-medium">{journeyTitle}</h2></div>
            <button type="button" onClick={() => setOpen(false)} aria-label="Collapse Getting Started"><X className="h-4 w-4" /></button>
          </header>
          <div className="min-h-0 overflow-y-auto p-5">
            {error && <p role="alert" className="mb-4 border border-[var(--color-error)]/30 p-3 text-xs text-[var(--color-error)]">{error}</p>}
            {state.activeJourney === null && <JourneyPicker onDemo={() => void startDemo()} onSetup={() => void startSetup()} onTour={() => void startTour()} />}
            {state.activeJourney === "demo" && <DemoJourney state={state} demo={demo} busy={busy} onStart={() => void startDemo()} onTour={() => void startTour()} onSetup={() => void startSetup()} />}
            {state.activeJourney === "setup" && (
              <SetupJourney step={selectedSetupStep} unlockedStep={setupStep} onSelect={setSelectedSetupStep} project={setupProject} ready={ready} teamName={teamName} setTeamName={setTeamName} busy={busy} organization={organization} memberCount={memberships?.data?.length || 0} invitationCount={invitations?.data?.length || 0} onCreateTeam={() => void createSetupTeam()} onImported={handleSetupProjectImported} onLinked={() => void refreshSetup()} onKey={() => { setHasTeamKey(true); void refreshSetup(); }} onInvited={() => void invitations?.revalidate?.()} onSkipInvite={() => void persist({ ...state, setup: { ...state.setup, invitationSkipped: true } })} onReady={async () => { if (!setupProject || !ready) return; await setDefaultStandaloneChatProject(setupProject.id); await startTour(); }} />
            )}
            {state.activeJourney === "tour" && <TourJourney step={selectedTourStep} unlockedStep={tourStep} pathname={pathname} spotlight={spotlight} onSelect={setSelectedTourStep} onNext={() => void nextTourStep()} />}
          </div>
          <footer className="sticky bottom-0 flex items-center justify-between border-t border-[var(--color-border)] bg-[var(--color-bg-card)] px-5 py-3">
            <button type="button" onClick={() => { if (session?.id) sessionStorage.setItem(hiddenForSessionKey(session.id), "1"); setHidden(true); }} className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)]">Hide for now</button>
            {state.activeJourney && <button type="button" onClick={() => void persist({ ...state, activeJourney: null })} className="text-[11px] text-[var(--color-text-dim)] hover:text-[var(--color-text)]">All journeys</button>}
          </footer>
        </aside>
      )}
    </>
  );
}

function JourneyPicker({ onDemo, onSetup, onTour }: { onDemo: () => void; onSetup: () => void; onTour: () => void }) {
  return <div className="space-y-3"><button onClick={onDemo} className="w-full border border-[var(--color-success)]/40 p-4 text-left"><span className="text-[10px] uppercase text-[var(--color-success)]">Recommended</span><strong className="mt-1 block text-sm">Explore a demo</strong><span className="text-xs text-[var(--color-text-dim)]">See SignalPilot answer a real analytics question.</span></button><button onClick={onSetup} className="w-full border border-[var(--color-border)] p-4 text-left"><strong className="text-sm">Connect my data</strong><span className="mt-1 block text-xs text-[var(--color-text-dim)]">Set up a production Team and dbt project.</span></button><button onClick={onTour} className="w-full border border-[var(--color-border)] p-4 text-left"><strong className="text-sm">Product Tour</strong></button></div>;
}

function DemoJourney({ state, demo, busy, onStart, onTour, onSetup }: { state: SignalPilotGettingStarted; demo: DemoBootstrapResponse | null; busy: boolean; onStart: () => void; onTour: () => void; onSetup: () => void }) {
  if (!state.demo.teamId) return <button onClick={onStart} disabled={busy} className="flex items-center gap-2 bg-[var(--color-text)] px-4 py-2 text-xs text-[var(--color-bg)]">{busy && <Loader2 className="h-3 w-3 animate-spin" />}Show me</button>;
  const active = demo?.phase === "project" ? 2 : demo?.phase === "opening" ? 3 : 1;
  return <div className="space-y-4"><ol className="space-y-3">{DEMO_PHASES.map((label, index) => <li key={label} className={`flex items-center gap-3 text-xs ${index <= active ? "text-[var(--color-text)]" : "text-[var(--color-text-dim)]"}`}>{index < active || demo?.status === "ready" ? <Check className="h-3.5 w-3.5 text-[var(--color-success)]" /> : index === active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <span className="h-3.5 w-3.5 rounded-full border border-[var(--color-border)]" />}{label}</li>)}</ol>{demo?.status === "ready" && <div className="space-y-2 border-t border-[var(--color-border)] pt-4"><p className="text-xs">{demo.requests_remaining} of {demo.request_limit} live requests remaining.</p><button onClick={onTour} className="mr-2 bg-[var(--color-text)] px-3 py-2 text-xs text-[var(--color-bg)]">Start Product Tour</button><button onClick={onSetup} className="border border-[var(--color-border)] px-3 py-2 text-xs">Set up my data</button></div>}</div>;
}

function SetupJourney(props: { step: number; unlockedStep: number; onSelect: (step: number) => void; project: WorkspaceProjectInfo | null; ready: boolean; teamName: string; setTeamName: (value: string) => void; busy: boolean; organization: OrganizationResource | null | undefined; memberCount: number; invitationCount: number; onCreateTeam: () => void; onImported: (project?: WorkspaceProjectInfo) => void; onLinked: (name: string) => void; onKey: () => void; onInvited: () => void; onSkipInvite: () => void; onReady: () => void }) {
  return (
    <div className="space-y-4">
      <ol className="grid grid-cols-2 gap-2">
        {SETUP_STEPS.map((label, index) => (
          <li key={label}>
            <button type="button" disabled={index > props.unlockedStep} onClick={() => props.onSelect(index)} className={`w-full text-left text-[11px] disabled:opacity-35 ${index <= props.unlockedStep ? "text-[var(--color-text)]" : "text-[var(--color-text-dim)]"}`}>
              {index < props.unlockedStep ? "✓ " : `${index + 1}. `}{label}
            </button>
          </li>
        ))}
      </ol>
      <div className="border-t border-[var(--color-border)] pt-4">
        {props.step < props.unlockedStep ? (
          <p className="flex items-center gap-2 text-xs text-[var(--color-text-muted)]"><Check className="h-3.5 w-3.5 text-[var(--color-success)]" />{SETUP_STEPS[props.step]} is complete.</p>
        ) : <>
        {props.step === 0 && (
          <div className="flex gap-2">
            <input value={props.teamName} onChange={(event) => props.setTeamName(event.target.value)} placeholder="Team name" className="flex-1 border border-[var(--color-border)] bg-[var(--color-bg-input)] px-3 py-2 text-xs" />
            <button onClick={props.onCreateTeam} disabled={props.busy || !props.teamName.trim()} className="bg-[var(--color-text)] px-4 py-2 text-xs text-[var(--color-bg)]">Create Team</button>
          </div>
        )}
        {props.step === 1 && <GitHubImportForm onClose={() => undefined} onImported={props.onImported} oauthReturnTo="/dashboard" />}
        {props.step === 2 && props.project && <SetupConnectionForm projectId={props.project.id} onLinked={props.onLinked} />}
        {props.step === 3 && <div className="border border-[var(--color-border)]"><AnthropicKeyForm onSaved={(value) => { if (value.has_key) props.onKey(); }} /></div>}
        {props.step === 4 && props.organization && (
          <div>
            <p className="mb-3 text-xs text-[var(--color-text-dim)]">Free capacity: owner plus one invited Admin. Active and pending invitations count.</p>
            {props.memberCount + props.invitationCount < 2
              ? <TeamInvitationForm org={props.organization} defaultRole={ROLE_ADMIN} onInvited={props.onInvited} />
              : <p className="text-xs">Team capacity is full.</p>}
            <button onClick={props.onSkipInvite} className="px-3 py-2 text-xs text-[var(--color-text-dim)]">Skip for now</button>
          </div>
        )}
        {props.step === 5 && (
          <div>
            <p className="mb-3 text-xs text-[var(--color-text-dim)]">{props.ready ? "Your tagged project, healthy warehouse, compiled dbt metadata, and Team key are ready." : "SignalPilot is waiting for a healthy warehouse connection and compiled dbt metadata."}</p>
            <button onClick={props.onReady} disabled={!props.project || !props.ready} className="bg-[var(--color-text)] px-4 py-2 text-xs text-[var(--color-bg)] disabled:opacity-40">Try Agent</button>
          </div>
        )}
        </>}
      </div>
    </div>
  );
}

function TourJourney({ step, unlockedStep, pathname, spotlight, onSelect, onNext }: { step: TourStep; unlockedStep: TourStep; pathname: string; spotlight: DOMRect | null; onSelect: (step: TourStep) => void; onNext: () => void }) {
  const current = TOUR_STEPS[step];
  const onPage = routeCompletesTourStep(pathname, step);
  return <div><ol className="space-y-1">{TOUR_STEPS.map((item, index) => <li key={item.href}><button type="button" disabled={!canSelectStep(index, unlockedStep)} onClick={() => onSelect(index as TourStep)} className="w-full px-2 py-2 text-left text-xs disabled:opacity-35">{index < unlockedStep ? "✓ " : `${index + 1}. `}{item.title}</button></li>)}</ol><div className="mt-4 border-t border-[var(--color-border)] pt-4"><h3 className="text-sm font-medium">{current.title}</h3><p className="mt-2 text-xs text-[var(--color-text-dim)]">{current.title === "Team" ? "Invite teammates and manage collaboration. Demo Teams are personal; create a production Team to collaborate." : `See how ${current.title.toLowerCase()} fits into the governed analytics workflow.`}</p>{onPage && !spotlight && <p className="mt-2 text-[11px] text-[var(--color-warning)]">This target is unavailable, but you can continue.</p>}<button onClick={onNext} className="mt-4 bg-[var(--color-text)] px-4 py-2 text-xs text-[var(--color-bg)]">{onPage ? step === 5 ? "Finish tour" : "Next" : `Open ${current.title}`}</button></div></div>;
}
