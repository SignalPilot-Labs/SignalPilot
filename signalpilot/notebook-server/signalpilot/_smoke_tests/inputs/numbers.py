import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md(r"""## Basic""")
    return


@app.cell
def _(sp):
    sp.ui.number()
    return


@app.cell
def _(sp):
    sp.ui.number(-10, 10)
    return


@app.cell
def _(sp):
    sp.md(r"""## Edge cases""")
    return


@app.cell
def _(sp):
    # Above max safe int
    BAD_INT = 999999999999999990
    v = sp.ui.number(
        value=BAD_INT, start=BAD_INT - 5, stop=BAD_INT + 5, full_width=True
    )
    v
    return (v,)


@app.cell
def _(v):
    v.value
    return


@app.cell
def _(sp):
    def on_change(new_value):
        print(new_value)


    sp.ui.number(start=-1e255, stop=1e255, value=5, on_change=on_change)
    return (on_change,)


@app.cell
def _(sp, on_change):
    import numpy as np

    # Cannot set infinity as range
    sp.ui.number(start=-np.inf, stop=np.inf, value=5, on_change=on_change)
    return


if __name__ == "__main__":
    app.run()
