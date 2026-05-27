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
    get_v, set_v = sp.state(True)
    get_v2, set_v2 = sp.state(True)
    return get_v, get_v2, set_v, set_v2


@app.cell
def _(get_v, get_v2):
    [get_v(), get_v2()]
    return


@app.cell
def _(get_v, sp, set_v):
    x = sp.ui.checkbox(get_v(), on_change=set_v)
    x
    return


@app.cell
def _(get_v, sp, set_v):
    y = sp.ui.checkbox(get_v(), on_change=set_v)
    y
    return


@app.cell
def _(get_v2, sp, set_v2):
    sp.ui.checkbox(get_v2(), on_change=set_v2)
    return


@app.cell
def _(get_v2, sp, set_v2):
    sp.ui.checkbox(get_v2(), on_change=set_v2)
    return


if __name__ == "__main__":
    app.run()
