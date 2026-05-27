# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    checkbox = sp.ui.checkbox(label="Full width")
    checkbox.callout()
    return (checkbox,)


@app.cell
def _(checkbox, sp):
    sp.ui.text(label="Text", full_width=checkbox.value)
    return


@app.cell
def _(checkbox, sp):
    sp.ui.text_area(label="Text area", full_width=checkbox.value)
    return


@app.cell
def _(checkbox, sp):
    sp.ui.number(0, 10, label="Number", full_width=checkbox.value)
    return


@app.cell
def _(checkbox, sp):
    sp.ui.dropdown(label="Dropdown", options=["A", "B", "C"], full_width=checkbox.value)
    return


@app.cell
def _(checkbox, sp):
    sp.ui.multiselect(label="Multiselect", options=["A", "B", "C"], full_width=checkbox.value)
    return


@app.cell
def _(checkbox, sp):
    sp.ui.date(label="Date", full_width=checkbox.value)
    return


@app.cell
def _(checkbox, sp):
    sp.ui.button(label="Button", full_width=checkbox.value)
    return


@app.cell
def _(checkbox, sp):
    # Is this the behavior we want?
    sp.hstack([
        sp.ui.text(label="Input A", full_width=checkbox.value),
        sp.ui.text(label="Input B", full_width=checkbox.value)
    ])
    return


@app.cell
def _(checkbox, sp):
    sp.vstack([
        sp.ui.text(label="Input A", full_width=checkbox.value),
        sp.ui.text(label="Input B", full_width=checkbox.value)
    ])
    return


if __name__ == "__main__":
    app.run()
