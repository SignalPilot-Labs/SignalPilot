# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "altair==5.5.0",
#     "sp",
#     "vega-datasets==0.9.0",
#     "vegafusion[embed]==2.0.1",
#     "vl-convert-python==1.7.0",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import altair as alt
    from vega_datasets import data

    import signalpilot

    alt.data_transformers.enable("vegafusion")

    # Load some data
    cars = data.cars()

    # Create an Altair chart
    _chart = (
        alt.Chart(cars)
        .mark_point()
        .encode(
            x="Horsepower",
            y="Miles_per_Gallon",
            color="Origin",
        )
        .properties(height=300)
        .add_params(alt.selection_interval(name="interval"))
    )

    # Make it reactive ⚡
    chart = sp.ui.anywidget(alt.JupyterChart(_chart))
    return (chart,)


@app.cell
def _(chart):
    chart
    return


@app.cell
def _(chart):
    list(chart.selections.interval.value.items())
    return


if __name__ == "__main__":
    app.run()
