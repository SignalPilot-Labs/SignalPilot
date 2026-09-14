import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { ALL_SCOPES } from "./api-key-scopes";

describe("API key scope choices", () => {
  it("matches every user-creatable backend scope exactly", () => {
    const source = readFileSync(
      path.resolve(process.cwd(), "../gateway/gateway/models/api_keys.py"),
      "utf8",
    );
    const definition = source.match(/VALID_API_KEY_SCOPES[^=]*=\s*frozenset\(\{([^}]+)\}\)/);
    expect(definition).not.toBeNull();
    const backendScopes = [...definition![1].matchAll(/"([^"]+)"/g)].map((match) => match[1]);
    expect(ALL_SCOPES.map((scope) => scope.value).sort()).toEqual(backendScopes.sort());
  });

  it("gives each unique choice a label and permission description", () => {
    expect(new Set(ALL_SCOPES.map((scope) => scope.value)).size).toBe(ALL_SCOPES.length);
    for (const scope of ALL_SCOPES) {
      expect(scope.label.trim()).not.toBe("");
      expect(scope.description.trim()).not.toBe("");
    }
  });
});
