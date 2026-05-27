import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    source = sp.ui.text()
    source
    return (source,)


@app.cell
def _(sp, source):
    sp.ui.file_browser(initial_path=source.value)
    return


@app.cell
def _(sp):
    from vega_datasets import data

    df = data.cars()
    columns = df.columns.tolist()
    slider = sp.ui.slider(0, len(columns), label="frozen columns")
    slider
    return columns, df, slider


@app.cell
def _(columns, df, sp, slider):
    frozen = columns[: slider.value]
    sp.ui.table(df, freeze_columns_left=frozen)
    return


if __name__ == "__main__":
    app.run()
