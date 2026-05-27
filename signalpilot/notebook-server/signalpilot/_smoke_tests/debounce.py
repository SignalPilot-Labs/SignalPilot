
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    slider = sp.ui.slider(1, 10, label="Slider")
    debounced_slider = sp.ui.slider(1, 10, debounce=True, label="Debounced Slider")

    number = sp.ui.number(1, 10, label="Number")
    debounced_number = sp.ui.number(1, 10, debounce=True, label="Debounced Number")
    return debounced_number, debounced_slider, number, slider


@app.cell
def _(debounced_number, debounced_slider, sp, number, slider):
    sp.md(f"""
        Controls:

        {slider}

        {debounced_slider}

        {number}

        {debounced_number}
    """)
    return


@app.cell
def _(debounced_number, debounced_slider, sp, number, slider):
    # Values
    sp.md(f"""
        slider: {slider.value}

        debounced slider: {debounced_slider.value}

        number: {number.value}

        debounced number: {debounced_number.value}
    """)
    return


@app.cell
def _(debounced_number, debounced_slider, sp, number, slider):
    sp.md(f"""
        Controls and Values:

        {slider} -> {slider.value}

        {debounced_slider} -> {debounced_slider.value}

        {number} -> {number.value}

        {debounced_number} -> {debounced_number.value}
    """)
    return


if __name__ == "__main__":
    app.run()
