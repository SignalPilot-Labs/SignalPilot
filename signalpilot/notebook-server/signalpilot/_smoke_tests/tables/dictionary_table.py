# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import os
    import signalpilot
    return sp, os


@app.cell
def _(sp, os):
    v = sp.ui.table(dict(os.environ))
    v
    return (v,)


@app.cell
def _(sp):
    sp.ui.table(
        {
            "a": 1,
            "b": 2,
        },
        format_mapping={
            "value": lambda x: x + 1,
        },
    )
    return


@app.cell
def _(v):
    v.value
    return


if __name__ == "__main__":
    app.run()
