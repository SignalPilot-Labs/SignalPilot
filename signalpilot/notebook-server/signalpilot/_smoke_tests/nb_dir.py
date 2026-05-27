import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    print("__file__", __file__)
    return


@app.cell
def _(sp):
    print("sp.notebook_dir()", sp.notebook_dir())
    return


if __name__ == "__main__":
    app.run()
