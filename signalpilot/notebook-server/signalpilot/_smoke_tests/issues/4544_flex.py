import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""## Buttons""")
    return


@app.cell
def _(sp):
    full_width = sp.ui.checkbox(label="Full width")
    full_width
    return (full_width,)


@app.cell
def _(full_width, sp):
    items = [
        sp.ui.button(label="button", full_width=full_width.value),
        sp.ui.text(label="button"),
    ]
    return (items,)


@app.cell
def _(items, sp):
    sp.vstack(items)
    return


@app.cell
def _(items, sp):
    sp.hstack(items)
    return


@app.cell
def _(items, sp):
    different_height_items = [
        *items,
        sp.ui.text_area(label="button"),
    ]
    return (different_height_items,)


@app.cell
def _(different_height_items, sp):
    sp.vstack(different_height_items)
    return


@app.cell
def _(different_height_items, sp):
    sp.hstack(different_height_items)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""## Sliders""")
    return


@app.cell(hide_code=True)
def _(full_width):
    full_width
    return


@app.cell
def _(full_width, sp):
    range_slider = sp.ui.range_slider(
        start=1, stop=10, step=2, value=[2, 6], full_width=full_width.value
    )
    range_slider
    return (range_slider,)


@app.cell
def _(sp, range_slider):
    sp.hstack([range_slider])
    return


@app.cell
def _(sp, range_slider):
    sp.vstack([range_slider])
    return


@app.cell
def _(full_width, sp):
    slider = sp.ui.slider(start=1, stop=10, step=2, full_width=full_width.value)
    slider
    return (slider,)


@app.cell
def _(sp, slider):
    sp.hstack([slider])
    return


@app.cell
def _(sp, slider):
    sp.vstack([slider])
    return


if __name__ == "__main__":
    app.run()
