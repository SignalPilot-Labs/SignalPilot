import { describe, expect, it } from "vitest";

import {
  buildProjectEditorHref,
  buildProjectEditorNavigationHref,
} from "./project-editor-link";

const project = "1dbf5492-81e6-4683-835f-f1785c9cfe78";
const branch = "main";
const file = "dbt_project.yml";

describe("project editor links", () => {
  it("builds the canonical share URL", () => {
    expect(buildProjectEditorHref({ project, branch, file })).toBe(
      `/projects?project=${project}&branch=main&file=dbt_project.yml`,
    );
  });

  it("keeps file navigation on the projects surface", () => {
    expect(
      buildProjectEditorNavigationHref({
        currentHref: `http://localhost:3200/projects?project=${project}`,
        project,
        branch,
        file,
      }),
    ).toBe(
      `http://localhost:3200/projects?project=${project}&branch=main&file=dbt_project.yml`,
    );
  });

  it("keeps file navigation on the exact fullscreen surface", () => {
    expect(
      buildProjectEditorNavigationHref({
        currentHref: `http://localhost:3200/notebook?project=${project}`,
        project,
        branch,
        file,
      }),
    ).toBe(
      `http://localhost:3200/notebook?project=${project}&branch=main&file=dbt_project.yml`,
    );
  });

  it("never treats a runtime proxy prefix as a browser page", () => {
    expect(
      buildProjectEditorNavigationHref({
        currentHref:
          `http://localhost:3200/notebook/0ef3b60e-e3e0-483f-9188-782750488e67?project=${project}`,
        project,
        branch,
        file,
      }),
    ).toBe(
      `http://localhost:3200/projects?project=${project}&branch=main&file=dbt_project.yml`,
    );
  });
});
