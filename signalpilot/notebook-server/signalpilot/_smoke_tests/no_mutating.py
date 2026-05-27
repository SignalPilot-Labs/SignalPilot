# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    text = sp.ui.text(on_change=print)
    return (text,)


@app.cell
def _(text):
    text.on_change
    return


@app.cell
def _(text):
    text.value = ""
    return


@app.cell
def _(text):
    text.on_change = ""
    return


if __name__ == "__main__":
    app.run()
