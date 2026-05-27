import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import altair as alt
    import pandas as pd
    import polars as pl

    import signalpilot

    df = pd.DataFrame(
        {
            "state": ["000", "010", "100", "111"],
            "count": [1, 2, 3, 4],
            "date": ["2023-01-01", "2023-01-02", "2023-01-03", "2023-01-04"],
        }
    )
    pl_df = pl.DataFrame(df)

    pd_chart = (
        alt.Chart(df)
        .mark_line()
        .encode(x="state:O", y="date:T")
        .properties(width=200)
    )
    pl_chart = (
        alt.Chart(pl_df)
        .mark_line()
        .encode(x="state:O", y="date:T")
        .properties(width=200)
    )

    sp.hstack([pd_chart, pl_chart])
    return alt, sp, pd_chart, pl_chart


@app.cell
def _(alt, sp, pd_chart, pl_chart):
    with alt.data_transformers.enable("signalpilot_csv"):
        sp.output.append(sp.hstack([pd_chart, pl_chart]))
    return


@app.cell
def _(alt, sp, pd_chart, pl_chart):
    with alt.data_transformers.enable("signalpilot_json"):
        sp.output.append(sp.hstack([pd_chart, pl_chart]))
    return


@app.cell
def _(alt, sp, pd_chart, pl_chart):
    with alt.data_transformers.enable("signalpilot_inline_csv"):
        sp.output.append(sp.hstack([pd_chart, pl_chart]))
    return


@app.cell
def _(alt, sp, pd_chart, pl_chart):
    with alt.data_transformers.enable("sp"):
        sp.output.append(sp.hstack([pd_chart, pl_chart]))
    return


@app.cell
def _(alt, sp, pd_chart, pl_chart):
    # This currently errors since Altair does internal validation, and 'arrow' is not a supported "type"
    with alt.data_transformers.enable("signalpilot_arrow"):
        sp.output.append(sp.hstack([pd_chart, pl_chart]))
    return


@app.cell
def _(sp, pd_chart, pl_chart):
    sp.hstack([sp.ui.altair_chart(pd_chart), sp.ui.altair_chart(pl_chart)])
    return


if __name__ == "__main__":
    app.run()
