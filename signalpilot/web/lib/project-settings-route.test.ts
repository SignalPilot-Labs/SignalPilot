import { describe, expect, it } from "vitest";

import { projectSettingsHref } from "./project-settings-route";

describe("projectSettingsHref", () => {
  it("opens the selected project's connection settings directly", () => {
    expect(projectSettingsHref("project/with spaces")).toBe(
      "/projects/project%2Fwith%20spaces/settings",
    );
  });

  it("falls back to the project overview when no project is selected", () => {
    expect(projectSettingsHref(null)).toBe("/projects");
  });
});
