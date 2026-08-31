"""Static chart rendering for standalone chat artifacts."""

from __future__ import annotations

import base64
import io
import math
from typing import Any

from signalpilot._server.ai.standalone_chat_chart_theme import (
    CHART_BACKGROUND,
    CHART_BORDER,
    CHART_COLORS,
    CHART_GRID,
    CHART_MUTED_TEXT,
    CHART_TEXT,
    chart_field,
    chart_mark_type,
    prepare_signalpilot_chart,
)


def _render_chart_png(
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    truncated: bool = False,
) -> str | None:
    if not rows:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

        spec, rows, _ = prepare_signalpilot_chart(spec, rows)
        encoding = spec.get("encoding") or {}
        x_field = chart_field(encoding.get("x"))
        y_field = chart_field(encoding.get("y"))
        color_field = chart_field(encoding.get("color"))
        if not x_field or not y_field:
            return None

        mark = chart_mark_type(spec)
        horizontal_bar = (
            mark == "bar"
            and (encoding.get("x") or {}).get("type") == "quantitative"
            and (encoding.get("y") or {}).get("type") != "quantitative"
        )
        figure, axis = plt.subplots(
            figsize=(8, 5),
            dpi=150,
            facecolor=CHART_BACKGROUND,
        )
        axis.set_facecolor(CHART_BACKGROUND)
        if color_field:
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                groups.setdefault(str(row.get(color_field, "")), []).append(
                    row
                )
        else:
            groups = {"": rows}

        def numeric(value: Any) -> float:
            if value is None or isinstance(value, bool):
                return math.nan
            try:
                number = float(value)
            except (TypeError, ValueError):
                return math.nan
            return number if math.isfinite(number) else math.nan

        def compact_number(value: float, _position: float) -> str:
            absolute = abs(value)
            for scale, suffix in (
                (1_000_000_000_000, "T"),
                (1_000_000_000, "B"),
                (1_000_000, "M"),
                (1_000, "k"),
            ):
                if absolute >= scale:
                    return f"{value / scale:.3g}{suffix}"
            return f"{value:.3g}"

        if mark == "bar":
            category_field = y_field if horizontal_bar else x_field
            value_field = x_field if horizontal_bar else y_field
            categories = list(
                dict.fromkeys(
                    str(row.get(category_field, "â€”")) for row in rows
                )
            )
            positions = list(range(len(categories)))
            category_positions = {
                category: position
                for category, position in zip(
                    categories, positions, strict=True
                )
            }
            group_count = len(groups)
            width = min(0.72 / max(group_count, 1), 0.72)
            for index, (label, group) in enumerate(groups.items()):
                values_by_category = {
                    str(row.get(category_field, "â€”")): numeric(
                        row.get(value_field)
                    )
                    for row in group
                }
                offsets = [
                    category_positions[category]
                    + (index - (group_count - 1) / 2) * width
                    for category in categories
                ]
                values = [
                    values_by_category.get(category, math.nan)
                    for category in categories
                ]
                kwargs = {
                    "color": CHART_COLORS[index % len(CHART_COLORS)],
                    "label": label if color_field else None,
                    "zorder": 3,
                }
                if horizontal_bar:
                    axis.barh(
                        offsets,
                        values,
                        height=width * 0.9,
                        **kwargs,
                    )
                else:
                    axis.bar(
                        offsets,
                        values,
                        width=width * 0.9,
                        **kwargs,
                    )
            display_categories = [
                category if len(category) <= 28 else f"{category[:27]}â€¦"
                for category in categories
            ]
            if horizontal_bar:
                axis.set_yticks(positions, display_categories)
                axis.invert_yaxis()
            else:
                axis.set_xticks(positions, display_categories)
        else:
            for index, (label, group) in enumerate(groups.items()):
                x_values = [row.get(x_field) for row in group]
                y_values = [numeric(row.get(y_field)) for row in group]
                color = CHART_COLORS[index % len(CHART_COLORS)]
                kwargs = {
                    "label": label if color_field else None,
                    "color": color,
                    "zorder": 3,
                }
                if mark == "line":
                    axis.plot(
                        x_values,
                        y_values,
                        marker="o",
                        linewidth=2.5,
                        markersize=4.5,
                        **kwargs,
                    )
                else:
                    valid = [
                        (x_value, y_value)
                        for x_value, y_value in zip(
                            x_values, y_values, strict=True
                        )
                        if not math.isnan(y_value)
                    ]
                    axis.scatter(
                        [value[0] for value in valid],
                        [value[1] for value in valid],
                        s=38,
                        edgecolors=CHART_BACKGROUND,
                        linewidths=0.8,
                        **kwargs,
                    )

        def axis_title(channel: Any, fallback: str) -> str:
            if not isinstance(channel, dict):
                return fallback
            axis_config = channel.get("axis")
            if isinstance(axis_config, dict) and axis_config.get("title"):
                return str(axis_config["title"])
            return str(channel.get("title") or fallback)

        axis.set_xlabel(axis_title(encoding.get("x"), x_field))
        axis.set_ylabel(axis_title(encoding.get("y"), y_field))
        axis.set_title(
            str(spec.get("title") or ""),
            loc="left",
            color=CHART_TEXT,
            fontsize=13,
            fontweight=600,
            pad=14,
        )
        axis.xaxis.label.set_color(CHART_TEXT)
        axis.yaxis.label.set_color(CHART_TEXT)
        axis.xaxis.label.set_size(10)
        axis.yaxis.label.set_size(10)
        axis.tick_params(
            axis="both",
            colors=CHART_TEXT,
            labelsize=9,
            color=CHART_BORDER,
        )
        for spine in axis.spines.values():
            spine.set_color(CHART_BORDER)
        value_axis = "x" if horizontal_bar else "y"
        axis.grid(axis=value_axis, color=CHART_GRID, linewidth=0.8, zorder=0)
        if horizontal_bar:
            axis.axvline(0, color=CHART_BORDER, linewidth=0.9, zorder=1)
            axis.xaxis.set_major_formatter(FuncFormatter(compact_number))
        else:
            axis.axhline(0, color=CHART_BORDER, linewidth=0.9, zorder=1)
            axis.yaxis.set_major_formatter(FuncFormatter(compact_number))
        category_field = y_field if horizontal_bar else x_field
        labels = [str(row.get(category_field, "")) for row in rows]
        rotate_labels = not horizontal_bar and (
            len(set(labels)) > 8
            or max((len(label) for label in labels), default=0) > 12
        )
        if rotate_labels:
            plt.setp(axis.get_xticklabels(), rotation=45, ha="right")
        if color_field:
            handles, legend_labels = axis.get_legend_handles_labels()
            legend = figure.legend(
                handles,
                [
                    label if len(label) <= 24 else f"{label[:23]}â€¦"
                    for label in legend_labels
                ],
                title=color_field,
                loc="lower center",
                bbox_to_anchor=(0.5, 0.015),
                ncol=min(4, len(groups)),
                frameon=False,
                fontsize=8,
                title_fontsize=9,
            )
            if legend:
                legend.get_title().set_color(CHART_TEXT)
                for text in legend.get_texts():
                    text.set_color(CHART_TEXT)
        figure.subplots_adjust(
            left=0.29 if horizontal_bar else 0.12,
            right=0.975,
            top=0.86,
            bottom=(
                0.43
                if color_field and rotate_labels
                else 0.29
                if rotate_labels
                else 0.23
                if color_field
                else 0.16
            ),
        )
        if truncated:
            figure.text(
                0.99,
                0.985,
                "Data truncated by the governed query row limit.",
                fontsize=7,
                color=CHART_MUTED_TEXT,
                ha="right",
                va="top",
            )
        output = io.BytesIO()
        figure.savefig(
            output,
            format="png",
            facecolor=CHART_BACKGROUND,
        )
        plt.close(figure)
        return base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        return None
