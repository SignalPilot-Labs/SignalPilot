# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    from named_cells import display_slider, display_element
    return display_element, display_slider


@app.cell
def _(sp):
    sp.md("""**A cell that creates and shows a slider**""")
    return


@app.cell
def _(display_slider):
    slider_output, slider_defs = display_slider.run()
    slider_output
    return (slider_defs,)


@app.cell
def _(sp):
    sp.md("""_Notice that set-ui-element value requests make it into the defs_""")
    return


@app.cell
def _(slider_defs):
    slider_defs
    return


@app.cell
def _(slider_defs):
    slider_defs["slider"].value
    return


@app.cell
def _(sp):
    sp.md("""**A cell that shows a parametrizable UI element**""")
    return


@app.cell
def _(display_element, sp):
    text = sp.ui.text(placeholder="custom input")
    _o, _ = display_element.run(element=text)
    _o
    return (text,)


@app.cell
def _(text):
    text.value
    return


if __name__ == "__main__":
    app.run()
