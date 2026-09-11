import { applyHostContext } from "../src/host-theme";

describe("applyHostContext", () => {
  it("stamps display mode, safe-area insets and locale but never host colours", () => {
    const root = document.documentElement;
    applyHostContext(
      {
        theme: "light",
        displayMode: "pip",
        availableDisplayModes: ["inline", "pip"],
        styles: { variables: { "--color-background-primary": "#fff", "--font-sans": "Inter" } as never },
        safeAreaInsets: { top: 4, right: 0, bottom: 8, left: 0 },
        locale: "en-GB",
      } as never,
      root,
    );
    expect(root.dataset.hostTheme).toBe("light");
    expect(root.dataset.displayMode).toBe("pip");
    expect(root.style.getPropertyValue("--color-background-primary")).toBe("");
    expect(root.style.getPropertyValue("--sp-safe-bottom")).toBe("8px");
    expect(root.lang).toBe("en-GB");
  });

  it("leaves the document alone without a context", () => {
    const root = document.createElement("html");
    applyHostContext(undefined, root);
    expect(root.dataset.displayMode).toBeUndefined();
  });
});
