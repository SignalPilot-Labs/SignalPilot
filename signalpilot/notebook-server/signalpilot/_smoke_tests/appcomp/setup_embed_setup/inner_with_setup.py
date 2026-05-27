
import signalpilot

__generated_with = "0.18.4"
app = sp.App(width="medium")


with app.setup:
    import signalpilot


@app.cell
def _():
    inner_value = 42
    sp.md("# Inner App with Setup Cell")
    return (inner_value,)


@app.cell
def _(inner_value):
    sp.md(f"Inner value is: {inner_value}")
    return


if __name__ == "__main__":
    app.run()
