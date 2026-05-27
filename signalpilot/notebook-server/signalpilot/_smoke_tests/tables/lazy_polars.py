import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import polars as pl
    return sp, pl


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""Load data""")
    return


@app.cell
def _(pl):
    # ~1-2 seconds
    df = pl.scan_parquet(
        "hf://datasets/google-research-datasets/go_emotions/raw/train-00000-of-00001.parquet"
    )
    return (df,)


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""`sp.plain`""")
    return


@app.cell
def _(df, sp):
    # ~100-300ms
    sp.plain(df)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""**default formatter**""")
    return


@app.cell
def _(df):
    # ~100-300ms
    df
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""`sp.ui.table.lazy`""")
    return


@app.cell
def _(df, sp):
    # 50ms
    sp.ui.table.lazy(df)
    return


@app.cell
def _(df):
    df.collect_schema()
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""Using with `sp.ui.table`""")
    return


@app.cell
def _():
    # This will force the DF to load everything into memory
    # sp.ui.table(df)
    return


@app.cell(hide_code=True)
def _():
    # Define the emotions to visualize
    emotions = [
        "admiration",
        "amusement",
        "anger",
        "annoyance",
        "approval",
        "caring",
        "confusion",
        "curiosity",
        "desire",
        "disappointment",
        "disapproval",
        "disgust",
        "embarrassment",
        "excitement",
        "fear",
        "gratitude",
        "grief",
        "joy",
        "love",
        "nervousness",
        "optimism",
        "pride",
        "realization",
        "relief",
        "remorse",
        "sadness",
        "surprise",
        "neutral",
    ]
    return (emotions,)


@app.cell(hide_code=True)
def _(sp):
    create_chart = sp.ui.run_button(label="Create chart")
    create_chart
    return (create_chart,)


@app.cell(hide_code=True)
def _(create_chart, df, emotions, sp):
    sp.stop(not create_chart.value)

    import altair as alt

    # Melt the DataFrame to have a 'emotion' and 'intensity' column
    emotion_df = df.select(["rater_id"] + emotions).melt(
        id_vars="rater_id", variable_name="emotion", value_name="intensity"
    )

    # Collect the data into memory
    emotion_data = emotion_df.collect()

    # Create an Altair chart
    chart = (
        alt.Chart(emotion_data)
        .mark_bar()
        .encode(
            x="emotion:N",
            y="sum(intensity):Q",
            tooltip=["emotion:N", "sum(intensity):Q"],
        )
        .properties(title="Sum of Emotional Intensities", width=600, height=400)
        .interactive()
    )

    alt.data_transformers.enable("signalpilot_csv")
    chart
    return


if __name__ == "__main__":
    app.run()
