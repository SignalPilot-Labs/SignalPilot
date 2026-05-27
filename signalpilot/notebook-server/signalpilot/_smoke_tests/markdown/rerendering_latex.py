import signalpilot

__generated_with = "0.17.4"
app = sp.App(width="medium")


@app.cell
def _():
    return


@app.cell
def _(sp):
    a=sp.ui.table({"a":[1,2,3]},selection="single",initial_selection=[0])
    a
    return (a,)


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(a, sp):
    md = sp.md(f"$a={a.value["a"][0]}$")
    md
    return


if __name__ == "__main__":
    app.run()
