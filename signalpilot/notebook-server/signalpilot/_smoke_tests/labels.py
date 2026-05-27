# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.23.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot

    return (sp,)


@app.cell
def _(sp):
    sp.md("""
    # Label alignment smoke test

    Visually verify that labels render at the correct position relative to
    their controls across every `Labeled` configuration. See the comments
    in each cell for the expected vs. regression behavior.

    Related: PR #9100 (table label padding) and the switch/checkbox
    vertical-centering regression introduced by it.
    """)
    return


@app.cell
def _(sp):
    # Case 1 — Inline label, side alignment (the original regression).
    # Expected: each label's text is vertically centered with its control
    # (switch knob, checkbox box, radio dot all line up with the cap-height of
    # the label text).
    # Regression: label text appears below the control's vertical center.
    sp.vstack(
        [
            sp.md("### Case 1 — inline (side) labels"),
            sp.ui.switch(label="Switch"),
            sp.ui.checkbox(label="Checkbox"),
            sp.ui.radio(["A", "B", "C"], label="Inline radio", inline=True),
        ]
    )
    return


@app.cell
def _(sp):
    # Case 2 — Side labels with markdown content.
    # Expected: bold/italic/code render inline with the control, still
    # vertically centered.
    sp.vstack(
        [
            sp.md("### Case 2 — inline labels with markdown"),
            sp.ui.switch(label="**Bold** label"),
            sp.ui.checkbox(label="*Italic* label"),
            sp.ui.switch(label="Label with `code`"),
        ]
    )
    return


@app.cell
def _(sp):
    # Case 3 — Side labels that are long enough to wrap.
    # Expected: control sits centered against the multi-line label block; the
    # gap between label and control stays consistent.
    sp.vstack(
        [
            sp.md("### Case 3 — long inline labels"),
            sp.ui.switch(
                label=(
                    "A fairly long switch label that should still align "
                    "with the switch even when it wraps to multiple lines"
                )
            ),
            sp.ui.checkbox(
                label=(
                    "A fairly long checkbox label that should still align "
                    "with the checkbox even when it wraps to multiple lines"
                )
            ),
        ]
    )
    return


@app.cell
def _(sp):
    # Case 4 — Top labels (no full_width).
    # Expected: label sits flush left above each control with a small gap.
    sp.vstack(
        [
            sp.md("### Case 4 — top labels"),
            sp.ui.text(label="Text input"),
            sp.ui.number(0, 10, label="Number input"),
            sp.ui.dropdown(["A", "B", "C"], label="Dropdown"),
            sp.ui.radio(["A", "B", "C"], label="Stacked radio"),
            sp.ui.date(label="Date"),
        ]
    )
    return


@app.cell
def _(sp):
    # Case 5 — Top labels with full_width.
    # Expected: label flush-left above the full-width control; control spans
    # the cell width.
    sp.vstack(
        [
            sp.md("### Case 5 — full-width top labels"),
            sp.ui.text(label="Full width text", full_width=True),
            sp.ui.text_area(label="Full width text area", full_width=True),
            sp.ui.dropdown(
                ["A", "B", "C"], label="Full width dropdown", full_width=True
            ),
            sp.ui.multiselect(
                ["A", "B", "C"], label="Full width multiselect", full_width=True
            ),
        ]
    )
    return


@app.cell
def _(sp):
    # Case 6 — Markdown headings as labels.
    # Expected: the heading renders at full size; flush-left.
    sp.vstack(
        [
            sp.md("### Case 6 — markdown headings as labels"),
            sp.ui.text(label="# H1 label", full_width=True),
            sp.ui.text(label="## H2 label", full_width=True),
            sp.ui.text(label="### H3 label", full_width=True),
        ]
    )
    return


@app.cell
def _(sp):
    # Case 7 — Table labels (PR #9100 case).
    # Expected: the label aligns with the table's first-column cell content
    # (i.e. it inherits `--sp-table-edge-padding` because the cell output
    # is a single flush table). This is what the wrapper `<div part="label">`
    # exists for.
    sp.ui.table(
        data=[
            {"Name": "Alice", "Score": 95, "Grade": "A"},
            {"Name": "Bob", "Score": 82, "Grade": "B"},
        ],
        label="Table",
    )
    return


@app.cell
def _(sp):
    # Case 8 — Table with a markdown heading label (PR #9100's "Cars dataset"
    # case).
    # Expected: the heading renders at h1 size and aligns with the table's
    # first-column content edge.
    sp.ui.table(
        data=[
            {"Name": "Alice", "Score": 95, "Grade": "A"},
            {"Name": "Bob", "Score": 82, "Grade": "B"},
        ],
        label="# Heading label",
    )
    return


@app.cell
def _(sp):
    # Case 9 — Table inside a vstack (NOT flush with the cell output).
    # Expected: no edge padding is applied; label flush-left at 0.
    sp.vstack(
        [
            sp.md("### Case 9 — table inside a container (not flush)"),
            sp.ui.table(
                data=[
                    {"Name": "Alice", "Score": 95, "Grade": "A"},
                    {"Name": "Bob", "Score": 82, "Grade": "B"},
                ],
                label="Non-flush table label",
            ),
        ]
    )
    return


@app.cell
def _(sp):
    # Case 10 — Code editor (uses align="top" fullWidth=true).
    # Expected: label flush-left above the editor; editor spans full width.
    sp.ui.code_editor(value="print('hello')", label="Code editor")
    return


@app.cell
def _(sp):
    # Case 11 — Stack of side-labeled controls in an hstack.
    # Expected: each switch/checkbox text remains centered with its control;
    # they don't visually drift relative to one another.
    sp.hstack(
        [
            sp.ui.switch(label="One"),
            sp.ui.switch(label="Two"),
            sp.ui.checkbox(label="Three"),
            sp.ui.checkbox(label="Four"),
        ],
        justify="start",
    )
    return


@app.cell
def _(sp):
    # Case 12 — Empty / no label sanity check.
    # Expected: control renders without any leading whitespace or vertical
    # offset; layout matches an explicitly labeled control's control area.
    sp.vstack(
        [
            sp.md("### Case 12 — no labels"),
            sp.ui.switch(),
            sp.ui.checkbox(),
            sp.ui.text(),
            sp.ui.dropdown(["A", "B", "C"]),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
