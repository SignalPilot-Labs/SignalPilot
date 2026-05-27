# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    from inner import app
    return (app,)


@app.cell
def _(sp):
    sp.md("# middle")
    return


@app.cell
def _(sp, result):
    x_plus_y = result.defs['x'].value + result.defs['y'].value
    sp.md(f"The middle app has calculated `x_plus_y` ... try retrieving it")
    return


@app.cell
async def _(app):
    result = await app.embed()
    result.output
    return (result,)


if __name__ == "__main__":
    app.run()
