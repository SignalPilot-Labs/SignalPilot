# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(sp):
    b = sp.ui.run_button()
    b
    return (b,)


@app.cell
def _(sp):
    s = sp.ui.slider(1, 10)
    s
    return (s,)


@app.cell
def _(b, sp, s):
    sp.stop(not b.value, "Click `run` to submit the slider's value")

    s.value
    return


@app.cell
def _(b, sp):
    sp.stop(not b.value)

    import random
    random.randint(0, 1000)
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
