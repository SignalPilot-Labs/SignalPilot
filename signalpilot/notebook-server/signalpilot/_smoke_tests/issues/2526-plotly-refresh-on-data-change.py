#uvx --with plotly --with pandas --with 'sp==0.9' sp edit plotly_signalpilot.py

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _(sp):
    a = sp.ui.checkbox(label="toggle to change data")
    a
    return (a,)


@app.cell
def _(a, np, px):
    x = np.array([1, 2, 3, 4]) if a.value else np.arange(3, 20)
    y = np.sin(x / 5)
    px.scatter(x=x, y=y)
    return x, y


@app.cell
def _(a):
    a
    return


@app.cell
def _(sp, px, x, y):
    plot = sp.ui.plotly(px.scatter(x=x, y=y)); plot
    return (plot,)


@app.cell
def _(plot):
    plot.value
    return


@app.cell
def _():
    import plotly.express as px
    import signalpilot
    import numpy as np
    return sp, np, px


if __name__ == "__main__":
    app.run()
