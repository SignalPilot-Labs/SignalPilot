import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    # Precision should be accurate, no rounding
    sp.ui.slider(
        label="1/1000 precision value",
        start=0,
        stop=0.1,
        step=0.001,
        value=0.025,
        show_value=True,
    )
    return


@app.cell
def _(sp):
    # Precision should be accurate, no rounding
    sp.ui.slider(
        label="1/1000 precision value",
        start=0,
        stop=0.0001,
        step=0.000001,
        value=0.000025,
        show_value=True,
    )
    return


if __name__ == "__main__":
    app.run()
