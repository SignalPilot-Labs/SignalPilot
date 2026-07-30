/**
 * Regression tests for `sanitizeHtml`.
 *
 * `sanitizeHtml` is applied to NOTEBOOK OUTPUT (attacker-influencable HTML), so
 * these tests pin both halves of the contract:
 *   1. the custom elements the app depends on (`sp-*`, `iconify-icon`) survive
 *      sanitization, including the `SAFE_FOR_XML: false` mermaid path;
 *   2. everything else that DOMPurify is there to remove still gets removed.
 *
 * Added alongside the dompurify 3.4.11 -> 3.4.12 upgrade, which fixes
 * GHSA "CUSTOM_ELEMENT_HANDLING bypasses afterSanitizeElements for allowed
 * custom elements" — the config in sanitize-html.ts enables
 * CUSTOM_ELEMENT_HANDLING, so this file guards against a behaviour change in
 * either direction.
 */
import { describe, expect, it } from "vitest";

import { sanitizeHtml } from "./sanitize-html";

const lower = (html: string) => sanitizeHtml(html).toLowerCase();

describe("sanitizeHtml — allowed custom elements survive", () => {
  it("keeps sp-* custom elements", () => {
    const out = lower('<sp-ui-element object-id="abc">hello</sp-ui-element>');
    expect(out).toContain("<sp-ui-element");
    expect(out).toContain('object-id="abc"');
    expect(out).toContain("hello");
  });

  it("keeps other sp-* elements used by the notebook renderer", () => {
    for (const tag of ["sp-tex", "sp-lazy", "sp-replace"]) {
      const out = lower(`<${tag} class="x">body</${tag}>`);
      expect(out, `${tag} should survive sanitization`).toContain(`<${tag}`);
      expect(out).toContain("body");
    }
  });

  it("keeps iconify-icon and its attributes", () => {
    const out = lower('<iconify-icon icon="lucide:check" width="16"></iconify-icon>');
    expect(out).toContain("<iconify-icon");
    expect(out).toContain('icon="lucide:check"');
    expect(out).toContain('width="16"');
  });

  it("keeps sp-mermaid, which takes the SAFE_FOR_XML: false path", () => {
    // `SAFE_FOR_XML` is disabled only when the input mentions sp-mermaid;
    // this asserts that branch still renders the element and its graph body.
    const out = lower("<sp-mermaid>graph TD; A--&gt;B;</sp-mermaid>");
    expect(out).toContain("<sp-mermaid");
    expect(out).toContain("graph td");
  });

  it("still strips dangerous content on the sp-mermaid (SAFE_FOR_XML: false) path", () => {
    const out = lower(
      '<sp-mermaid>graph TD;</sp-mermaid><script>alert(1)</script><img src=x onerror="alert(2)">',
    );
    expect(out).toContain("<sp-mermaid");
    expect(out).not.toContain("<script");
    expect(out).not.toContain("onerror");
  });

  it("keeps SVG <use> and href/xlink:href (matplotlib SVG output)", () => {
    const out = lower(
      '<svg><defs><rect id="r" /></defs><use href="#r" xlink:href="#r" /></svg>',
    );
    expect(out).toContain("<use");
    expect(out).toContain("#r");
  });
});

describe("sanitizeHtml — disallowed content is stripped", () => {
  it("drops a custom element that does not match the tagNameCheck", () => {
    const out = lower("<evil-element>payload</evil-element>");
    expect(out).not.toContain("<evil-element");
    // DOMPurify keeps the text content, it only unwraps the element.
    expect(out).toContain("payload");
  });

  it("drops a look-alike that only prefixes the allowed pattern", () => {
    // `xsp-foo` and `spx-foo` must not satisfy /^sp-[A-Za-z][\w-]*$/.
    for (const tag of ["xsp-foo", "spx-foo", "sp--foo"]) {
      const out = lower(`<${tag}>payload</${tag}>`);
      expect(out, `${tag} must not be allowed`).not.toContain(`<${tag}`);
    }
  });

  it("strips script tags", () => {
    const out = lower('<div>ok</div><script>alert("xss")</script>');
    expect(out).not.toContain("<script");
    expect(out).not.toContain("alert(");
    expect(out).toContain("ok");
  });

  it("strips inline event handlers", () => {
    const out = lower('<img src="x" onerror="alert(1)">');
    expect(out).not.toContain("onerror");
    expect(out).not.toContain("alert(");
  });

  it("strips event handlers placed on an ALLOWED custom element", () => {
    // DOMPurify applies no event-handler filtering of its own to attributes
    // accepted via CUSTOM_ELEMENT_HANDLING.attributeNameCheck, so the app's
    // regex has to exclude `on*` itself. Highest-value regression assertion.
    for (const attr of ["onclick", "onerror", "ONCLICK", "onmouseover"]) {
      const out = lower(`<sp-ui-element ${attr}="alert(1)">x</sp-ui-element>`);
      expect(out).toContain("<sp-ui-element");
      expect(out, `${attr} must be stripped`).not.toContain(attr.toLowerCase());
      expect(out).not.toContain("alert(");
    }
  });

  it("still allows benign attributes on allowed custom elements", () => {
    const out = lower(
      '<sp-ui-element object-id="abc" data-x="1" random-attr="ok">x</sp-ui-element>',
    );
    expect(out).toContain('object-id="abc"');
    expect(out).toContain('data-x="1"');
    expect(out).toContain('random-attr="ok"');
  });

  it("allows attributes that merely start with the letters 'on' as a prefix of a word", () => {
    // Guard against over-tightening: `once` / `online` are not event handlers,
    // but the `(?!on)` lookahead does reject them. Pin the current behaviour
    // so a future relaxation is a deliberate, reviewed change.
    const out = lower('<sp-ui-element once="1">x</sp-ui-element>');
    expect(out).toContain("<sp-ui-element");
    expect(out).not.toContain("once=");
  });

  it("strips a nested script inside an allowed custom element", () => {
    const out = lower("<sp-ui-element><script>alert(1)</script></sp-ui-element>");
    expect(out).toContain("<sp-ui-element");
    expect(out).not.toContain("<script");
  });

  it("strips iframes", () => {
    // NOTE: `<form>` is intentionally NOT asserted here — it is part of
    // DOMPurify's `html` profile and survives by design, despite the stale
    // "removes form tags" comment on sanitizeHtml.
    const out = lower('<iframe src="https://example.invalid"></iframe>');
    expect(out).not.toContain("<iframe");
  });

  it("strips javascript: URLs", () => {
    const out = lower('<a href="javascript:alert(1)">click</a>');
    expect(out).not.toContain("javascript:");
  });
});

describe("sanitizeHtml — link target hooks", () => {
  it("adds rel=noopener noreferrer to target=_blank links", () => {
    const out = lower('<a href="https://example.test" target="_blank">x</a>');
    expect(out).toContain('target="_blank"');
    expect(out).toContain("noopener");
    expect(out).toContain("noreferrer");
  });

  it("defaults links without a target to _self and drops the temp attribute", () => {
    const out = lower('<a href="https://example.test">x</a>');
    expect(out).toContain('target="_self"');
    expect(out).not.toContain("data-temp-href-target");
  });
});
