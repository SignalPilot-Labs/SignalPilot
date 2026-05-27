import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    # BUG: interactive, repeated chart does not work with polars data frame, non interactive one works fine.
    return


@app.cell
def _():
    from datetime import date

    import altair as alt
    import polars as pl

    import signalpilot

    sample_data = pl.DataFrame(
        {
            "day": [date(2025, 1, 1), date(2025, 1, 2)],
            "value1": [10, 9],
            "value2": [100, 34],
        }
    )
    return alt, sp, sample_data


@app.cell
def _(alt, sp, sample_data):
    chart = (
        alt.Chart(sample_data)
        .mark_line()
        .encode(
            x=alt.X("day:T"),
            y=alt.Y(alt.repeat("column"), type="quantitative"),
        )
        .repeat(column=["value1", "value2"])
    )

    # expected output is to have two rows with same charts

    sp.vstack([chart, sp.ui.altair_chart(chart)])
    return


if __name__ == "__main__":
    app.run()
