# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
#     "pandas",
#     "numpy",
#     "vega-datasets",
#     "altair",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell(hide_code=True)
def _():
    import json

    import numpy as np
    import pandas as pd
    from vega_datasets import data

    import signalpilot
    return data, sp, np, pd


@app.cell
def _(data):
    # data
    cars = data.cars()
    employment = data.unemployment_across_industries.url
    iris = data.iris()
    return cars, employment, iris


@app.cell(hide_code=True)
def _(sp):
    chart_selection_type = sp.ui.radio(
        ["default", "point", "interval"],
        label="Selection Type",
        value="default",
    )
    theme = sp.ui.radio(
        ["default", "dark", "latimes"], label="Theme", value="default"
    )
    legend_selection_type = sp.ui.radio(
        ["all", "none"], label="Legend Selection Type", value="all"
    )

    sp.hstack([chart_selection_type, legend_selection_type, theme]).callout()
    return chart_selection_type, legend_selection_type, theme


@app.cell
def _(chart_selection_type, legend_selection_type, theme):
    import altair as alt

    alt.themes.enable(theme.value)
    chart_selection_value = (
        True
        if chart_selection_type.value == "default"
        else chart_selection_type.value
    )
    legend_selection_value = legend_selection_type.value == "all"
    None
    return alt, chart_selection_value, legend_selection_value


@app.cell
def _(alt, cars, chart_selection_value, legend_selection_value, sp):
    _chart = (
        alt.Chart(cars)
        .mark_point()
        .encode(
            x="Horsepower",
            y="Miles_per_Gallon",
            color="Origin",
        )
    )
    chart1 = sp.ui.altair_chart(
        _chart,
        chart_selection=chart_selection_value,
        legend_selection=legend_selection_value,
        label="Cars",
    )
    return (chart1,)


@app.cell
def _(sp):
    sp.md("""# Basic Chart""")
    return


@app.cell
def _(alt, chart1, chart_selection_value, legend_selection_value, sp):
    sp.vstack(
        [
            chart1,
            (
                sp.ui.altair_chart(
                    alt.Chart(chart1.value)
                    .mark_bar()
                    .encode(
                        x="Origin",
                        y="count()",
                        color="Origin",
                    ),
                    chart_selection=chart_selection_value,
                    legend_selection=legend_selection_value,
                )
                if not chart1.value.empty
                else sp.md("No selection")
            ),
            chart1.value.head(),
        ]
    )
    return


@app.cell
def _(alt, chart_selection_value, employment, legend_selection_value, sp):
    # _selection = alt.selection_point(fields=["series"], bind="legend")

    _chart = (
        alt.Chart(employment)
        .mark_area()
        .encode(
            alt.X("yearmonth(date):T").axis(
                domain=False, format="%Y", tickSize=0
            ),
            alt.Y("sum(count):Q").stack("center").axis(None),
            alt.Color("series:N").scale(scheme="category20b"),
            # opacity=alt.condition(_selection, alt.value(1), alt.value(0.9)),
        )
    )
    # ).add_params(_selection)
    chart2 = sp.ui.altair_chart(
        _chart,
        chart_selection=chart_selection_value,
        legend_selection=legend_selection_value,
    )
    return (chart2,)


@app.cell
def _(sp):
    sp.md("""# Another Chart""")
    return


@app.cell
def _(chart2, sp):
    sp.vstack([chart2, chart2.value.head(10)])
    return


@app.cell
def _(sp):
    sp.md("""# Defined Width + Height""")
    return


@app.cell
def _(alt, iris, sp):
    _chart = (
        alt.Chart(iris)
        .mark_circle()
        .properties(width=600, height=400)
        .encode(
            alt.X("sepalLength", scale=alt.Scale(zero=False)),
            alt.Y("sepalWidth", scale=alt.Scale(zero=False)),
            color="species",
            size="petalWidth",
        )
    )

    sp.ui.altair_chart(
        _chart,
        chart_selection=None,
        legend_selection=None,
    )
    return


@app.cell
def _(alt, chart_selection_value, iris, legend_selection_value, sp):
    # _color_sel = alt.selection_point(fields=["species"], bind="legend")
    # _size_sel = alt.selection_point(fields=["petalWidth"], bind="legend")

    _chart = (
        alt.Chart(iris)
        .mark_circle(opacity=0.7)
        .encode(
            alt.X("sepalLength", scale=alt.Scale(zero=False)),
            alt.Y("sepalWidth", scale=alt.Scale(zero=False, padding=1)),
            color="species",
            size="petalWidth",
            # opacity=alt.condition(
            #     _color_sel & _size_sel, alt.value(1), alt.value(0.2)
            # ),
        )
        # .add_params(_color_sel, _size_sel)
    )

    chart3 = sp.ui.altair_chart(
        _chart,
        chart_selection=chart_selection_value,
        legend_selection=legend_selection_value,
    )
    return (chart3,)


@app.cell
def _(sp):
    sp.md("""# Chart + Chart""")
    return


@app.cell
def _(chart3, sp):
    sp.hstack([chart3, chart3])
    return


@app.cell
def _(sp):
    sp.md("""# Chart + Table""")
    return


@app.cell
def _(chart3, sp):
    sp.hstack([chart3, chart3.value.head(10)], widths="equal")
    return


@app.cell
def _(sp):
    sp.md("""# Chart + Table returned as an array""")
    return


@app.cell
def _(chart3):
    [chart3, chart3.value.head(10)]
    return


@app.cell
def _(alt, cars, chart_selection_value, legend_selection_value, sp):
    brush = alt.selection_interval()
    points = (
        alt.Chart(cars)
        .mark_point()
        .encode(
            x="Horsepower:Q",
            y="Miles_per_Gallon:Q",
            color=alt.condition(brush, "Origin:N", alt.value("lightgray")),
        )
        .add_params(brush)
    )
    bars = (
        alt.Chart(cars)
        .mark_bar()
        .encode(y="Origin:N", color="Origin:N", x="count(Origin):Q")
        .transform_filter(brush)
    )
    plot = points & bars
    chart4 = sp.ui.altair_chart(
        plot,
        chart_selection=chart_selection_value,
        legend_selection=legend_selection_value,
    )
    return (chart4,)


@app.cell
def _(sp):
    sp.md("""# Chart with transform""")
    return


@app.cell
def _(chart4, sp):
    sp.vstack([chart4, chart4.value.head(10)])
    return


@app.cell
def _(sp):
    sp.md("""# Bar chart""")
    return


@app.cell
def _(alt, data, sp):
    binned = sp.ui.altair_chart(
        alt.Chart(data.cars())
        .mark_bar()
        .encode(x=alt.X("Miles_per_Gallon:Q", bin=True), y="count()")
    )
    return


@app.cell
def _(alt, cars, sp):
    mean = sp.ui.altair_chart(
        alt.Chart(cars)
        .mark_bar()
        .encode(
            x="Cylinders:O",
            y="mean(Acceleration):Q",
        )
    )
    return (mean,)


@app.cell
def _(mean, sp):
    sp.vstack([mean, mean.value])
    return


@app.cell
def _(alt, data, sp):
    hist = (
        alt.Chart(data.cars())
        .mark_bar()
        .encode(x=alt.X("Miles_per_Gallon:Q"), y="count()")
    )
    hist = sp.ui.altair_chart(hist)
    return (hist,)


@app.cell
def _(hist, sp):
    sp.vstack([hist, hist.value])
    return


@app.cell
def _(sp):
    sp.md("""# Pivot and horizontal bar chart""")
    return


@app.cell
def _(alt, sp, pd):
    df = pd.DataFrame.from_records(
        [
            {"country": "Norway", "type": "gold", "count": 14},
            {"country": "Norway", "type": "silver", "count": 14},
            {"country": "Norway", "type": "bronze", "count": 11},
            {"country": "Germany", "type": "gold", "count": 14},
            {"country": "Germany", "type": "silver", "count": 10},
            {"country": "Germany", "type": "bronze", "count": 7},
            {"country": "Canada", "type": "gold", "count": 11},
            {"country": "Canada", "type": "silver", "count": 8},
            {"country": "Canada", "type": "bronze", "count": 10},
        ]
    )

    pivot = sp.ui.altair_chart(
        alt.Chart(df)
        .transform_pivot("type", groupby=["country"], value="count")
        .mark_bar()
        .encode(
            x="gold:Q",
            y="country:N",
        )
    )
    return (pivot,)


@app.cell
def _(sp, pivot):
    sp.vstack([pivot, pivot.value.head()])
    return


@app.cell
def _(alt, data, sp):
    _source = data.population.url

    horizontal_bar = sp.ui.altair_chart(
        alt.Chart(_source)
        .mark_bar()
        .encode(
            alt.X("sum(people):Q").title("Population"),
            alt.Y("age:O"),
        )
        .transform_filter(alt.datum.year == 2000)
        .properties(height=alt.Step(20))
    )
    return (horizontal_bar,)


@app.cell
def _(horizontal_bar, sp):
    sp.vstack([horizontal_bar, horizontal_bar.value.head()])
    return


@app.cell
def _(alt, sp, pd):
    _source = pd.DataFrame(
        {"category": [1, 2, 3, 4, 5, 6], "value": [4, 6, 10, 3, 7, 8]}
    )

    pie = sp.ui.altair_chart(
        alt.Chart(_source)
        .mark_arc(innerRadius=50)
        .encode(
            theta="value",
            color="category:N",
        )
    )
    return (pie,)


@app.cell
def _(sp, pie):
    sp.vstack([pie, pie.value])
    return


@app.cell
def _(sp):
    sp.md("""# Line Chart""")
    return


@app.cell
def _(alt, sp, np, pd):
    x = np.arange(100)
    source = pd.DataFrame({"x": x, "f(x)": np.sin(x / 5)})

    line_chart = sp.ui.altair_chart(
        alt.Chart(source).mark_line().encode(x="x", y="f(x)"),
        chart_selection="interval",
    )
    line_chart
    return (line_chart,)


@app.cell
def _(line_chart, sp):
    sp.hstack([line_chart.value, line_chart.selections])
    return


@app.cell
def _(sp):
    sp.md("""# Multi-Line Chart""")
    return


@app.cell
def _(alt, data, sp):
    _source = data.stocks()

    alt.Chart(_source).mark_line().encode(
        x="date:T",
        y="price:Q",
        color="symbol:N",
    )

    multiline_chart = sp.ui.altair_chart(
        alt.Chart(_source)
        .mark_line()
        .encode(
            x="date:T",
            y="price:Q",
            color="symbol:N",
        ),
    )
    multiline_chart
    return (multiline_chart,)


@app.cell
def _(sp, multiline_chart):
    sp.hstack([multiline_chart.value, multiline_chart.selections])
    return


@app.cell
def _(alt, sp, np, pd):
    # Example dataset
    _data = pd.DataFrame(
        {
            "date": pd.date_range(start="2021-01-01", periods=90, freq="D"),
            "value": np.random.randn(90).cumsum(),
            "category": ["A", "B", "C"] * 30,
            "color": ["red", "green", "blue"] * 30,
        }
    )

    # Create a base chart
    facet_chart = (
        alt.Chart(_data)
        .mark_line()
        .encode(
            x="date:T",  # T indicates temporal (time-based) data
            y="value:Q",  # Q indicates a quantitative field
            row="category:N",  # N indicates a nominal field
        )
        .properties(title="Faceted Time Series Chart")
        .configure_facet(spacing=10)  # Adjust spacing between facets
    )

    facet_chart = sp.ui.altair_chart(facet_chart, chart_selection="interval")
    facet_chart
    return (facet_chart,)


@app.cell
def _(facet_chart, sp):
    sp.hstack([facet_chart.value, facet_chart.selections])
    return


@app.cell
def _(sp):
    sp.md(
        """
        # With `transform_filter`
        > Bug https://docs.signalpilot.ai/docs/
        """
    )
    return


@app.cell
def _(alt, data, sp):
    from altair import datum

    _chart = (
        alt.Chart(data.cars())
        .mark_point()
        .encode(
            x="Horsepower",
            y="Miles_per_Gallon",
            color="Origin",
        )
        .transform_filter(datum.Origin == "Europe")
    )
    with_transform = sp.ui.altair_chart(_chart)
    return datum, with_transform


@app.cell
def _(sp, with_transform):
    sp.vstack([with_transform, with_transform.value])
    return


@app.cell
def _(sp):
    sp.md("""# Layers""")
    return


@app.cell
def _(alt, sp, pd):
    _source = pd.DataFrame(
        {
            "yield_error": [7.5522, 6.9775, 3.9167, 11.9732],
            "yield_center": [32.4, 30.96667, 33.966665, 30.45],
            "variety": ["Glabron", "Manchuria", "No. 457", "No. 462"],
        }
    )

    bar = (
        alt.Chart(_source)
        .mark_errorbar(ticks=True)
        .encode(
            x=alt.X("yield_center:Q").scale(zero=False).title("yield"),
            xError=("yield_error:Q"),
            y=alt.Y("variety:N"),
        )
        .properties(width="container")
    )

    point = (
        alt.Chart(_source)
        .mark_point(filled=True, color="black")
        .encode(
            alt.X("yield_center:Q"),
            alt.Y("variety:N"),
        )
    )

    _chart = bar + point
    # layered_chart = sp.ui.altair_chart(_chart, chart_selection="point")
    layered_chart = sp.ui.altair_chart(_chart, chart_selection="interval")
    return (layered_chart,)


@app.cell
def _(layered_chart, sp):
    sp.vstack(
        [
            layered_chart,
            sp.hstack([layered_chart.value, layered_chart.selections]),
        ]
    )
    return


@app.cell
def _(sp):
    sp.md(r"""# layered""")
    return


@app.cell
def _(alt, data, datum, sp):
    stocks = data.stocks.url

    base = (
        alt.Chart(stocks)
        .encode(x="date:T", y="price:Q", color="symbol:N")
        .transform_filter(datum.symbol == "GOOG")
    )

    t = sp.ui.altair_chart(base.mark_line() + base.mark_point())
    t
    return (base,)


@app.cell
def _(sp):
    sp.md(r"""# hconcat""")
    return


@app.cell
def _(base, sp):
    sp.ui.altair_chart(base.mark_line() | base.mark_point())
    return


@app.cell
def _(sp):
    sp.md("""# vconcat""")
    return


@app.cell
def _(base, sp):
    sp.ui.altair_chart(base.mark_line() & base.mark_point())
    return


if __name__ == "__main__":
    app.run()
