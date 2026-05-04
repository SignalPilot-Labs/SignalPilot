const numberFormatter = new Intl.NumberFormat();

export function formatNumber(value: unknown): string {
  if (typeof value === "number" && isFinite(value)) {
    return numberFormatter.format(value);
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (!isNaN(parsed) && isFinite(parsed)) {
      return numberFormatter.format(parsed);
    }
  }
  return String(value);
}
