import signalpilot

__generated_with = "0.19.2"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot
    import time
    return (sp,)


@app.cell
def _():
    state = None
    return (state,)


@app.cell
def _(sp):
    print("Creating slider")
    slider = sp.ui.slider(0, 10, 1, 3, label="A slider")
    return (slider,)


@app.cell
def _(slider):
    slider
    return


@app.cell
def _(slider, state):
    value = slider.value if state is None else state()
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
