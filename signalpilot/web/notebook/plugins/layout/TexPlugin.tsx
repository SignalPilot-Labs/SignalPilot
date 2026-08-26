import { type JSX, useLayoutEffect, useRef, useState } from "react";

import { z } from "zod";
import { once } from "@/utils/once";
import type {
  IStatelessPlugin,
  IStatelessPluginProps,
} from "../stateless-plugin";

/**
 * TexPlugin
 *
 * A plugin that renders LaTeX, specialized for how our kernel processes
 * LaTeX.
 */
export class TexPlugin implements IStatelessPlugin<{}> {
  tagName = "sp-tex";

  validator = z.object({});

  render(props: IStatelessPluginProps<{}>): JSX.Element {
    return (
      <TexComponent
        host={props.host}
        tex={props.host.textContent || props.host.innerHTML}
      />
    );
  }
}

const importKatex = once(async () => {
  return (await import("katex")).default;
});

const importMhChem = once(async () => {
  // @ts-expect-error : type is not exported by katex
  await import("katex/contrib/mhchem");
});

// Required, even if empty. (see https://github.com/KaTeX/KaTeX/issues/2513)
const macros = {
  // KaTeX doesn't support \mbox; map it to the equivalent \text
  "\\mbox": "\\text{#1}",
};

async function renderLatex(mount: HTMLElement, tex: string): Promise<void> {
  const [katex] = await Promise.all([importKatex(), importMhChem()]);
  if (tex.startsWith("||(||(") && tex.endsWith("||)||)")) {
    // when $$...$$ is used without newlines before/after the $$.
    katex.render(tex.slice(6, -6), mount, {
      displayMode: true,
      globalGroup: true,
      throwOnError: false,
      macros: macros,
    });
  } else if (tex.startsWith("||(") && tex.endsWith("||)")) {
    // Inline math, via $...$
    katex.render(tex.slice(3, -3), mount, {
      displayMode: false,
      globalGroup: true,
      throwOnError: false,
      macros: macros,
    });
  } else if (tex.startsWith("||[") && tex.endsWith("||]")) {
    // Display math, via $$...$$
    katex.render(tex.slice(3, -3), mount, {
      displayMode: true,
      globalGroup: true,
      throwOnError: false,
      macros: macros,
    });
  }
}

const TexComponent = ({
  host,
  tex,
}: {
  host: HTMLElement;
  tex: string;
}): JSX.Element => {
  const ref = useRef<HTMLSpanElement>(null);
  const [currentTex, setCurrentTex] = useState(tex);

  // Watch for changes to the host element's direct children
  useLayoutEffect(() => {
    const observer = new MutationObserver(() => {
      const newTex = host.textContent || host.innerHTML;
      setCurrentTex(newTex);
    });

    observer.observe(host, {
      childList: true,
      characterData: true,
      subtree: true,
    });

    return () => {
      observer.disconnect();
    };
  }, [host]);

  // The arithmatex markdown extension we use in Python produces nested
  // sp-tex tags when $$...$$ math is used in a paragraph, with dummy
  // children that mess with rendering.
  //
  // eg., sp.md("hello $$x$$") produces
  //
  // <sp-tex class="arithmatex">||(<sp-tex class="arithmatex">||(x||)</sp-tex>||)</sp-tex>
  //
  // while sp.md("$$x$$") produces the expected
  //
  // <sp-tex class="arithmatex">||[x||]</sp-tex>
  //
  // The nesting looks like a bug, or at least it makes rendering the latex
  // more annoying. So we just get rid of the nesting here, since there
  // isn't a simple way to do that in Python without bringing in a new
  // dependency.
  //
  // When nested, the inner sp-tex should not render because the outer
  // sp-tex's textContent includes the nested delimiters (||(||(x||)||))
  // and will render correctly with displayMode: true. We detect this by
  // checking if the parent element is also a sp-tex.
  const isNested = host.parentElement?.tagName.toLowerCase() === "sp-tex";

  // Re-render when the text content changes.
  useLayoutEffect(() => {
    if (ref.current && !isNested) {
      renderLatex(ref.current, currentTex);
    }
  }, [currentTex, isNested]);

  return <span ref={ref} />;
};
