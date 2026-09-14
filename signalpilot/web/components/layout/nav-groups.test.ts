import { describe, expect, it } from "vitest";

import * as icons from "~/components/layout/nav-icons";
import { nav, navGroups } from "~/components/layout/nav-groups";

describe("nav-groups", () => {
  it("flattens every group into nav in order", () => {
    expect(nav).toEqual(navGroups.flatMap((g) => g.items));
  });

  it("keeps hrefs unique and shortcuts unique when set", () => {
    const hrefs = nav.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    const shortcuts = nav.map((i) => i.shortcut).filter(Boolean);
    expect(new Set(shortcuts).size).toBe(shortcuts.length);
  });

  it("wires every item to an exported NavIcon component", () => {
    const exported = new Set<unknown>(Object.values(icons));
    for (const item of nav) {
      expect(typeof item.icon).toBe("function");
      expect(exported.has(item.icon)).toBe(true);
    }
  });

  it("starts with Dashboard and ends with Settings", () => {
    expect(nav[0]).toMatchObject({ href: "/dashboard", shortcut: "1" });
    expect(nav[nav.length - 1]).toMatchObject({ href: "/settings", shortcut: "0" });
  });
});
