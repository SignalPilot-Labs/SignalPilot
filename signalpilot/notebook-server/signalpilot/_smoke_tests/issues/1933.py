
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    from vega_datasets import data
    return (data,)


@app.cell
def _(data, sp):
    t = sp.ui.table(data.cars())
    return (t,)


@app.cell
def _(sp, t):
    dictionary = sp.ui.dictionary({
        "cars": t
    })
    id(dictionary["cars"]), dictionary
    return (dictionary,)


@app.cell
def _(dictionary):
    dictionary.value["cars"]
    return


if __name__ == "__main__":
    app.run()
