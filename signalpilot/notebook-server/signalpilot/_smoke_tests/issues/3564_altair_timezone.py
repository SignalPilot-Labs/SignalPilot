import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell(hide_code=True)
def _():
    import altair as alt
    import signalpilot
    import pandas as pd
    import polars as pl
    from datetime import datetime, timedelta, timezone
    return alt, datetime, sp, pd, pl, timedelta, timezone


@app.cell(hide_code=True)
def _(sp, pd, pl):
    df_lib_select = sp.ui.dropdown(
        {
            "pandas": pd,
            "polars": pl,
        },
        label="Dataframe library",
        value="pandas",
    )
    df_lib_select
    return (df_lib_select,)


@app.cell(hide_code=True)
def _(datetime, timedelta, timezone):
    # just creates 10 data points every hour, starting from 2024-08-30 00:00:00.000Z
    to_display = [
        {
            "datetime": datetime(
                year=2024, month=8, day=30, hour=0, tzinfo=timezone.utc
            )
            + timedelta(hours=i),
            "count": i + 1,
        }
        for i in range(10)
    ]
    return (to_display,)


@app.cell
def _(alt, df_lib_select, sp, timedelta, to_display):
    df_lib = df_lib_select.value

    df_buckets = df_lib.DataFrame(to_display)

    bars = (
        alt.Chart(df_buckets)
        .mark_bar(size=30)
        .encode(
            x=alt.X(
                "datetime:T",
                scale=alt.Scale(
                    # it just helps to see the difference
                    domain=[
                        to_display[0]["datetime"] - timedelta(hours=3),
                        to_display[-1]["datetime"] + timedelta(hours=1),
                    ],
                    type="utc",
                ),
                title="bucket",
            ),
            y="count:Q",
        )
        .properties(width=800, height=200)
    )
    chart = sp.ui.altair_chart(bars)
    return bars, chart


@app.cell
def _(bars):
    bars
    return


@app.cell
def _(chart):
    chart
    return


@app.cell
def _(alt, bars, sp):
    with alt.data_transformers.enable("signalpilot_json"):
        sp.output.replace(bars)
    return


@app.cell
def _(alt, bars, sp):
    with alt.data_transformers.enable("signalpilot_csv"):
        sp.output.replace(bars)
    return


@app.cell
def _(bars, sp):
    sp.ui.altair_chart(bars)
    return


@app.cell
def _(bars, sp):
    sp.iframe(bars.to_html())
    return


if __name__ == "__main__":
    app.run()
