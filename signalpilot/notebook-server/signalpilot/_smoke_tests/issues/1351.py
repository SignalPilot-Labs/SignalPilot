# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(sp):
    themes = ["dark_minimal", "light_minimal", "contrast", "night_sky", "caliber"]
    selected_theme = sp.ui.radio(themes, label="Theme", value="dark_minimal")
    selected_theme
    return (selected_theme,)


@app.cell
def _(selected_theme):
    import polars as pl
    import holoviews as hv
    import hvplot.polars

    hv.extension("bokeh")
    hvplot.extension("bokeh")
    hv.renderer("bokeh").theme = selected_theme.value
    return (pl,)


@app.cell
def _(pl):
    df = pl.DataFrame({"a": range(1, 10), "b": range(1, 10)})
    df.plot.line(
        x="a",
        y="b",
    )
    return


@app.cell
def _(selected_theme):
    from bokeh.plotting import curdoc, figure

    x = [1, 2, 3, 4, 5]
    y = [6, 7, 6, 4, 5]

    curdoc().theme = selected_theme.value

    p = figure(width=300, height=300)
    p.line(x, y)

    p
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
