"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { getSettings, updateSettings } from "~/lib/api";
import { cloneTheme, DEFAULT_DELIVERABLE_THEME, themeToCssVars } from "~/lib/deliverable-theme";
import type { DeliverableTheme, ThemeColors } from "~/lib/types";
import { useToast } from "~/components/ui/toast";

const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
const COLOR_FIELDS: { key: keyof ThemeColors; label: string }[] = [
  { key: "bg", label: "background" },
  { key: "surface", label: "surface" },
  { key: "surface_alt", label: "surface alt" },
  { key: "border", label: "border" },
  { key: "text", label: "text" },
  { key: "muted", label: "muted" },
  { key: "accent", label: "accent" },
  { key: "positive", label: "positive" },
  { key: "warning", label: "warning" },
  { key: "negative", label: "negative" },
  { key: "chart_grid", label: "chart grid" },
  { key: "chart_axis", label: "chart axis" },
];

function expandHex(value: string): string {
  if (/^#[0-9a-fA-F]{3}$/.test(value)) {
    return `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}`.toLowerCase();
  }
  return HEX_RE.test(value) ? value.toLowerCase() : "#000000";
}

function normalizeTheme(theme: DeliverableTheme | null | undefined): DeliverableTheme {
  const source = theme ?? DEFAULT_DELIVERABLE_THEME;
  const chartSeries = [...(source.chart_series?.length ? source.chart_series : []), ...DEFAULT_DELIVERABLE_THEME.chart_series].slice(0, 6);
  return cloneTheme({
    ...DEFAULT_DELIVERABLE_THEME,
    ...source,
    colors: { ...DEFAULT_DELIVERABLE_THEME.colors, ...source.colors },
    chart_series: chartSeries,
  });
}

function isForbidden(error: unknown): boolean {
  return String(error).includes("403");
}

function invalidTheme(theme: DeliverableTheme): boolean {
  return (
    COLOR_FIELDS.some(({ key }) => !HEX_RE.test(theme.colors[key])) ||
    theme.chart_series.some((color) => !HEX_RE.test(color)) ||
    !theme.font_family.trim()
  );
}

export function ThemeEditor() {
  const { toast } = useToast();
  const [draft, setDraft] = useState<DeliverableTheme>(() => cloneTheme(DEFAULT_DELIVERABLE_THEME));
  const [saved, setSaved] = useState<DeliverableTheme>(() => cloneTheme(DEFAULT_DELIVERABLE_THEME));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [adminLocked, setAdminLocked] = useState(false);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(saved), [draft, saved]);
  const hasErrors = invalidTheme(draft);
  const disabled = loading || saving || adminLocked;

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const settings = await getSettings();
        const next = normalizeTheme(settings.deliverable_theme);
        if (!active) return;
        setDraft(next);
        setSaved(cloneTheme(next));
        setAdminLocked(false);
      } catch (error) {
        if (!active) return;
        if (isForbidden(error)) {
          setAdminLocked(true);
        } else {
          toast(`failed to load theme: ${error}`, "error", 6000);
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, [toast]);

  function updateColor(key: keyof ThemeColors, value: string) {
    setDraft((theme) => ({ ...theme, colors: { ...theme.colors, [key]: value } }));
  }

  function updateSeries(index: number, value: string) {
    setDraft((theme) => {
      const next = [...theme.chart_series];
      next[index] = value;
      return { ...theme, chart_series: next };
    });
  }

  function updateNumber(key: "font_size_base_px" | "spacing_unit_px" | "radius_px", value: string) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed)) return;
    setDraft((theme) => ({ ...theme, [key]: parsed }));
  }

  async function saveTheme(nextTheme: DeliverableTheme | null) {
    setSaving(true);
    try {
      const current = await getSettings();
      const updated = await updateSettings({ ...current, deliverable_theme: nextTheme });
      const next = normalizeTheme(updated.deliverable_theme);
      setDraft(next);
      setSaved(cloneTheme(next));
      setAdminLocked(false);
      toast(nextTheme ? "theme saved" : "theme reset", "success");
    } catch (error) {
      if (isForbidden(error)) setAdminLocked(true);
      toast(`failed to save theme: ${error}`, "error", 6000);
    } finally {
      setSaving(false);
    }
  }

  async function handleSave() {
    if (hasErrors) {
      toast("fix invalid theme values before saving", "error");
      return;
    }
    await saveTheme(draft);
  }

  async function handleReset() {
    if (!window.confirm("Reset deliverable theme to SignalPilot defaults?")) return;
    await saveTheme(null);
  }

  return (
    <div className="border border-[var(--color-border)] bg-[var(--color-bg-card)] p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-5">
        <div>
          <p className="text-[13px] text-[var(--color-text)] tracking-wider">org deliverable tokens</p>
          {adminLocked && <p className="mt-1 text-[11px] text-[var(--color-error)] tracking-wider">org admin required</p>}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            disabled={disabled}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-text-dim)] border border-[var(--color-border)] hover:text-[var(--color-text)] hover:border-[var(--color-border-hover)] transition-all tracking-wider uppercase disabled:opacity-30"
          >
            <RotateCcw className="w-3 h-3" />
            reset
          </button>
          <button
            onClick={handleSave}
            disabled={disabled || !dirty || hasErrors}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] text-[var(--color-bg)] bg-[var(--color-text)] hover:opacity-90 transition-all tracking-wider uppercase disabled:opacity-30"
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
            save
          </button>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {COLOR_FIELDS.map(({ key, label }) => (
              <label key={key} className="block">
                <span className="block text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase mb-1.5">{label}</span>
                <div className="flex items-center border border-[var(--color-border)] bg-[var(--color-bg-input)]">
                  <input
                    type="color"
                    value={expandHex(draft.colors[key])}
                    onChange={(event) => updateColor(key, event.target.value)}
                    disabled={disabled}
                    className="h-9 w-10 bg-transparent border-0 p-1 disabled:opacity-30"
                  />
                  <input
                    value={draft.colors[key]}
                    onChange={(event) => updateColor(key, event.target.value)}
                    disabled={disabled}
                    className={`min-w-0 flex-1 bg-transparent px-2 py-2 font-mono text-[12px] outline-none disabled:opacity-30 ${
                      HEX_RE.test(draft.colors[key]) ? "text-[var(--color-text)]" : "text-[var(--color-error)]"
                    }`}
                  />
                </div>
              </label>
            ))}
          </div>

          <div>
            <p className="text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase mb-2">chart rank scale</p>
            <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {draft.chart_series.slice(0, 6).map((color, index) => (
                <label key={index} className="block">
                  <span className="block text-[10px] text-[var(--color-text-dim)] tracking-wider mb-1">
                    rank {index + 1}{index === 0 ? " highest" : ""}
                  </span>
                  <div className="flex items-center border border-[var(--color-border)] bg-[var(--color-bg-input)]">
                    <input
                      type="color"
                      value={expandHex(color)}
                      onChange={(event) => updateSeries(index, event.target.value)}
                      disabled={disabled}
                      className="h-9 w-10 bg-transparent border-0 p-1 disabled:opacity-30"
                    />
                    <input
                      value={color}
                      onChange={(event) => updateSeries(index, event.target.value)}
                      disabled={disabled}
                      className={`min-w-0 flex-1 bg-transparent px-2 py-2 font-mono text-[12px] outline-none disabled:opacity-30 ${
                        HEX_RE.test(color) ? "text-[var(--color-text)]" : "text-[var(--color-error)]"
                      }`}
                    />
                  </div>
                </label>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_120px_120px_120px]">
            <label className="block">
              <span className="block text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase mb-1.5">font family</span>
              <input
                value={draft.font_family}
                onChange={(event) => setDraft((theme) => ({ ...theme, font_family: event.target.value }))}
                disabled={disabled}
                className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[12px] text-[var(--color-text)] font-mono outline-none disabled:opacity-30"
              />
            </label>
            <NumberField label="font px" value={draft.font_size_base_px} min={10} max={24} disabled={disabled} onChange={(value) => updateNumber("font_size_base_px", value)} />
            <NumberField label="space px" value={draft.spacing_unit_px} min={4} max={24} disabled={disabled} onChange={(value) => updateNumber("spacing_unit_px", value)} />
            <NumberField label="radius px" value={draft.radius_px} min={0} max={24} disabled={disabled} onChange={(value) => updateNumber("radius_px", value)} />
          </div>
        </div>

        <Preview theme={draft} />
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="block text-[11px] text-[var(--color-text-dim)] tracking-wider uppercase mb-1.5">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="w-full px-3 py-2 bg-[var(--color-bg-input)] border border-[var(--color-border)] text-[12px] text-[var(--color-text)] font-mono outline-none disabled:opacity-30"
      />
    </label>
  );
}

function Preview({ theme }: { theme: DeliverableTheme }) {
  const barHeights = [42, 68, 35, 82, 55];
  const ranks = barHeights
    .map((height, index) => ({ height, index }))
    .sort((a, b) => b.height - a.height)
    .reduce<Record<number, number>>((acc, item, rank) => {
      acc[item.index] = rank + 1;
      return acc;
    }, {});

  return (
    <div style={themeToCssVars(theme)} className="bg-[var(--sp-bg)] border border-[var(--sp-border)] p-[var(--sp-space-2)] text-[var(--sp-text)] font-[var(--sp-font)] text-[length:var(--sp-font-size)]">
      <div className="sp-dashboard">
        <div className="sp-kpi-grid grid grid-cols-2 gap-[var(--sp-space-2)] mb-[var(--sp-space-2)]">
          <div className="sp-kpi-card bg-[var(--sp-surface)] border border-[var(--sp-border)] p-[var(--sp-space-2)]" style={{ borderRadius: "var(--sp-radius)" }}>
            <div className="sp-kpi-label text-[var(--sp-muted)] text-[11px] uppercase tracking-wider">revenue</div>
            <div className="sp-kpi-value">$2.4m</div>
            <div className="sp-delta-up text-[12px]">+18.2%</div>
          </div>
          <div className="sp-kpi-card bg-[var(--sp-surface)] border border-[var(--sp-border)] p-[var(--sp-space-2)]" style={{ borderRadius: "var(--sp-radius)" }}>
            <div className="sp-kpi-label text-[var(--sp-muted)] text-[11px] uppercase tracking-wider">risk</div>
            <div className="sp-kpi-value">low</div>
            <div className="sp-delta-down text-[12px]">-3 pts</div>
          </div>
        </div>
        <div className="sp-chart-card mb-[var(--sp-space-2)] bg-[var(--sp-surface)] border border-[var(--sp-border)] p-[var(--sp-space-2)]" style={{ borderRadius: "var(--sp-radius)" }}>
          <div className="flex items-center justify-between text-[12px]">
            <span>pipeline</span>
            <span className="text-[var(--sp-muted)]">q4</span>
          </div>
          <div className="h-28 flex items-end gap-2 border-l border-b border-[var(--sp-chart-grid)] px-2">
            {barHeights.map((height, index) => {
              const rank = ranks[index] ?? barHeights.length;
              return (
                <div
                  key={index}
                  className="flex-1"
                  style={{
                    height: `${height}%`,
                    background: `var(--sp-chart-${rank})`,
                    borderRadius: "var(--sp-radius) var(--sp-radius) 0 0",
                  }}
                />
              );
            })}
          </div>
        </div>
        <div className="sp-table-wrap">
          <table className="sp-data-table text-[12px]">
            <thead>
              <tr className="bg-[var(--sp-surface-alt)] text-[var(--sp-muted)]">
                <th className="border-b border-[var(--sp-border)] p-[var(--sp-space)] text-left">segment</th>
                <th className="border-b border-[var(--sp-border)] p-[var(--sp-space)] text-left">score</th>
                <th className="border-b border-[var(--sp-border)] p-[var(--sp-space)] text-left">delta</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="border-b border-[var(--sp-border)] p-[var(--sp-space)]">enterprise</td>
                <td className="border-b border-[var(--sp-border)] p-[var(--sp-space)]">91</td>
                <td className="sp-delta-up border-b border-[var(--sp-border)] p-[var(--sp-space)]">+8</td>
              </tr>
              <tr>
                <td className="border-b border-[var(--sp-border)] p-[var(--sp-space)]">mid market</td>
                <td className="border-b border-[var(--sp-border)] p-[var(--sp-space)]">74</td>
                <td className="sp-delta-down border-b border-[var(--sp-border)] p-[var(--sp-space)]">-2</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
