import { describe, expect, it } from "vitest";
import {
  canSelectStep,
  deriveSetupStep,
  hiddenForSessionKey,
  normalizeGettingStarted,
  routeCompletesTourStep,
  shouldShowGettingStarted,
} from "~/lib/getting-started";

describe("getting started state", () => {
  it("upgrades missing and malformed metadata to v2", () => {
    expect(normalizeGettingStarted(undefined)).toMatchObject({
      version: 2,
      activeJourney: null,
      demo: { replaySeen: false },
      setup: { invitationSkipped: false },
      tour: { status: "not_started", step: 0 },
    });
    expect(normalizeGettingStarted({ activeJourney: "setup", setup: { teamId: "org_1" }, tour: { step: 99 } }))
      .toMatchObject({ activeJourney: "setup", setup: { teamId: "org_1" }, tour: { step: 5 } });
  });

  it("blocks future steps but keeps current and complete steps selectable", () => {
    expect(canSelectStep(0, 2)).toBe(true);
    expect(canSelectStep(2, 2)).toBe(true);
    expect(canSelectStep(3, 2)).toBe(false);
  });

  it("completes only the expected tour route", () => {
    expect(routeCompletesTourStep("/connections", 1)).toBe(true);
    expect(routeCompletesTourStep("/connections/new", 1)).toBe(true);
    expect(routeCompletesTourStep("/schema", 1)).toBe(false);
  });

  it("keys hiding to the Clerk session", () => {
    expect(hiddenForSessionKey("sess_a")).not.toBe(hiddenForSessionKey("sess_b"));
  });

  it("does not surface an automatic controller for existing users", () => {
    expect(shouldShowGettingStarted(false, null, false)).toBe(false);
    expect(shouldShowGettingStarted(false, null, true)).toBe(true);
    expect(shouldShowGettingStarted(false, "tour", false)).toBe(true);
    expect(shouldShowGettingStarted(true, "setup", true)).toBe(false);
  });

  it("derives setup from Team resources instead of metadata counters", () => {
    expect(deriveSetupStep({ teamMatches: true, hasProject: true, hasLinkedConnection: true, hasTeamKey: true, invitationSkipped: false, invitationCount: 0, memberCount: 1 })).toBe(4);
    expect(deriveSetupStep({ teamMatches: true, hasProject: true, hasLinkedConnection: true, hasTeamKey: true, invitationSkipped: false, invitationCount: 1, memberCount: 1 })).toBe(5);
    expect(deriveSetupStep({ teamMatches: true, hasProject: true, hasLinkedConnection: true, hasTeamKey: true, invitationSkipped: false, invitationCount: 0, memberCount: 2 })).toBe(5);
  });
});
