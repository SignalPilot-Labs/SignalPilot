import signalpilot

__generated_with = "0.18.4"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    slider = sp.ui.slider(0, 10, 1, 3, label="A slider")
    slider
    return (slider,)


@app.cell
def _(slider):
    value = slider.value
    label = "our"
    return label, value


@app.cell
def _():
    kind = "info"
    return (kind,)


@app.cell
def _(kind, label, sp, value):
    sp.callout(
        sp.md(f"""
        The value of *{label}* slider is **{value}**!
        """), kind
    )
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()