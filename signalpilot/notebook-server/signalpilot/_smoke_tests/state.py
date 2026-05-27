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
def _():
    import math
    return (math,)


@app.cell
def _():
    import random
    return


@app.cell
def _():
    import time
    return


@app.cell
def _(sp):
    get_state, set_state = sp.state(0)
    return get_state, set_state


@app.cell
def _(get_state, set_state):
    # No self-loops: shouldn't be a cycle
    set_state(get_state())
    return


@app.cell
def _(get_state):
    get_state()
    return


@app.cell
def _(sp, set_state):
    _on_click = lambda _: set_state(lambda v: v + 1)
    button = sp.ui.button(
        value=0, on_click=_on_click
    )
    button
    return


@app.cell
def _(sp):
    # tie two number components together
    get_angle, set_angle = sp.state(0)
    return get_angle, set_angle


@app.cell
def _(get_angle, sp, set_angle):
    degrees = sp.ui.number(
        0, 360, step=1, value=get_angle(), on_change=set_angle, label="degrees"
    )
    return (degrees,)


@app.cell
def _(get_angle, math, sp, set_angle):
    radians = sp.ui.number(
        0,
        2*math.pi,
        step=0.01,
        value=get_angle() * math.pi / 180,
        on_change=lambda v: set_angle(v * 180 / math.pi),
        label="radians"
    )
    return (radians,)


@app.cell
def _(degrees, radians):
    degrees, radians
    return


if __name__ == "__main__":
    app.run()
