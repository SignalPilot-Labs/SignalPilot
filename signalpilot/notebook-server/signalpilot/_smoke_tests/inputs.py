# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    disabled = sp.ui.switch(label="Disabled")
    sp.hstack([disabled])
    return (disabled,)


@app.cell
def _(disabled, sp):
    sp.vstack(
        [
            sp.ui.text(label="Your name", disabled=disabled.value),
            sp.ui.text(
                label="Your tagline", max_length=30, disabled=disabled.value
            ),
            sp.ui.text_area(
                label="Your bio", max_length=180, disabled=disabled.value
            ),
        ]
    )
    return


@app.cell
def _(sp):
    options = ["red", "green", "blue"]

    sp.vstack(
        [
            sp.ui.dropdown(options, label="Dropdown"),
            sp.ui.multiselect(options, label="Multi-select"),
        ]
    )
    return (options,)


@app.cell
def _(sp, options):
    sp.ui.radio(options, label="Radio buttons")
    return


@app.cell
def _(sp, options):
    sp.ui.radio(options, label="Radio buttons", inline=True)
    return


@app.cell
def _(sp):
    slider = sp.ui.slider(0, 10, label="Horizontal slider")
    vslider = sp.ui.slider(0, 10, orientation="vertical", label="Vertical slider")
    sp.hstack([slider, vslider])
    return


@app.cell
def _(sp):
    _slider = sp.ui.slider(0, 100, label="Horizontal slider", show_value=True)
    _vslider = sp.ui.slider(
        0, 100, orientation="vertical", label="Vertical slider", show_value=True
    )
    sp.hstack([_slider, _vslider])
    return


if __name__ == "__main__":
    app.run()
