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
    return


@app.cell
def _(sp):
    slider = sp.ui.slider(1, 5)
    slider
    return (slider,)


@app.cell
def _(sp, slider):
    import plotly.express as px
    x_data = [1,2,3,4,5,6][:slider.value]
    y_data = [1,2,3,2,3,4][:slider.value]
    fig = px.scatter(x=x_data, y=y_data)

    p = sp.ui.plotly(fig)
    p
    return (p,)


@app.cell
def _(p):
    p.value
    return


if __name__ == "__main__":
    app.run()
