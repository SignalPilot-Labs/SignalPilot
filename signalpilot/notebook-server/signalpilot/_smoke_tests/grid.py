
import signalpilot

__generated_with = "0.15.5"
app = sp.App(layout_file="layouts/grid.grid.json")


@app.cell
def _(sp):
    align = sp.ui.dropdown(
        label="Align", options=["start", "end", "center", "stretch"]
    )
    justify = sp.ui.dropdown(
        label="Justify",
        options=["start", "center", "end", "space-between", "space-around"],
    )
    gap = sp.ui.number(label="Gap", start=0, stop=100, value=1)
    size = sp.ui.slider(label="Size", start=60, stop=500)
    wrap = sp.ui.checkbox(label="Wrap")

    sp.hstack([align, justify, gap, size, wrap], gap=0.25)
    return align, gap, justify, size, wrap


@app.cell
def _(sp):
    sp.md("""# Horizontal Stack: `hstack`""")
    return


@app.cell
def _(align, boxes, gap, justify, sp, wrap):
    sp.hstack(
        boxes,
        align=align.value,
        justify=justify.value,
        gap=gap.value,
        wrap=wrap.value,
    )
    return


@app.cell
def _(sp):
    sp.md("""# Vertical Stack: `vstack`""")
    return


@app.cell
def _(align, boxes, gap, sp):
    sp.vstack(
        boxes,
        align=align.value,
        gap=gap.value,
    )
    return


@app.cell
def _(sp, size):
    def create_box(num):
        box_size = size.value + num * 10
        return sp.Html(
            f"<div style='min-width: {box_size}px; min-height: {box_size}px; background-color: orange; text-align: center; line-height: {box_size}px'>{str(num)}</div>"
        )


    boxes = [create_box(i) for i in range(1, 5)]
    return (boxes,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
