# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    from state import app
    return (app,)


@app.cell
async def _(app):
    (await app.embed()).output
    return


if __name__ == "__main__":
    app.run()
