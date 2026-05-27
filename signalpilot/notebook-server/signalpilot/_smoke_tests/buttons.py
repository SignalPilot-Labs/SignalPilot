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
    kinds = ["neutral", "success", "warn", "danger"]

    sp.vstack([sp.ui.button(label=kind, kind=kind) for kind in kinds])
    return (kinds,)


@app.cell
def _(kinds, sp):
    sp.vstack([sp.ui.button(label=kind, kind=kind, disabled=True) for kind in kinds])
    return


if __name__ == "__main__":
    app.run()
