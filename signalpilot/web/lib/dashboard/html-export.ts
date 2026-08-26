function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function activeStyles(): string {
  return Array.from(document.styleSheets)
    .flatMap((sheet) => {
      try {
        return Array.from(sheet.cssRules, (rule) => rule.cssText);
      } catch {
        return [];
      }
    })
    .join("\n");
}

function preserveFormState(source: HTMLElement, clone: HTMLElement): void {
  const sourceFields = source.querySelectorAll<
    HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
  >("input, select, textarea");
  const clonedFields = clone.querySelectorAll<
    HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
  >("input, select, textarea");
  sourceFields.forEach((field, index) => {
    const cloned = clonedFields[index];
    if (!cloned) return;
    if (field instanceof HTMLInputElement) {
      cloned.setAttribute("value", field.value);
      if (field.checked) cloned.setAttribute("checked", "");
      else cloned.removeAttribute("checked");
      return;
    }
    if (field instanceof HTMLTextAreaElement) {
      cloned.textContent = field.value;
      return;
    }
    if (
      !(field instanceof HTMLSelectElement) ||
      !(cloned instanceof HTMLSelectElement)
    )
      return;
    Array.from(cloned.options).forEach((option, optionIndex) => {
      if (optionIndex === field.selectedIndex)
        option.setAttribute("selected", "");
      else option.removeAttribute("selected");
    });
  });
}

function captureCanvases(source: HTMLElement, clone: HTMLElement): void {
  const canvases = source.querySelectorAll("canvas");
  const clonedCanvases = clone.querySelectorAll("canvas");
  canvases.forEach((canvas, index) => {
    const cloned = clonedCanvases[index];
    if (!cloned) return;
    try {
      const image = document.createElement("img");
      image.src = canvas.toDataURL("image/png");
      image.alt = canvas.getAttribute("aria-label") ?? "Dashboard chart";
      image.width = canvas.clientWidth || canvas.width;
      image.height = canvas.clientHeight || canvas.height;
      image.style.cssText = canvas.style.cssText;
      image.style.maxWidth = "100%";
      cloned.replaceWith(image);
    } catch {
      // The surrounding exact-result UI remains in the cloned dashboard.
    }
  });
}

export function captureDashboardHtmlExport({
  root,
  title,
  sourceUrl,
  exportedAt = new Date(),
}: {
  root: HTMLElement;
  title: string;
  sourceUrl: string;
  exportedAt?: Date;
}): string {
  const clone = root.cloneNode(true) as HTMLElement;
  preserveFormState(root, clone);
  captureCanvases(root, clone);
  clone
    .querySelectorAll("[data-dashboard-export-exclude]")
    .forEach((element) => element.remove());
  clone.setAttribute("data-dashboard-static-export", "true");
  const styles = activeStyles();
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title)}</title><style>${styles}\nhtml,body{margin:0;min-height:100%;background:#0c1118}[data-dashboard-static-export]{min-height:100vh}[data-dashboard-static-export] button,[data-dashboard-static-export] summary{pointer-events:none}</style></head><body>${clone.outerHTML}<footer style="padding:16px 32px;background:#0c1118;color:#9ba7b5;font:11px system-ui;border-top:1px solid #283240">Offline governed snapshot exported ${escapeHtml(exportedAt.toISOString())} · Source ${escapeHtml(sourceUrl)} · This file contains the visible dashboard data and makes no API calls.</footer></body></html>`;
}
