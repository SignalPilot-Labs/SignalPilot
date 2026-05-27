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
    dict1={"hello": sp.ui.text(label="world")}
    dict2=sp.ui.dictionary({k: v.form() for k, v in dict1.items()})
    dict2
    return (dict2,)


@app.cell
def _(dict2):
    dict2.value
    return


if __name__ == "__main__":
    app.run()
