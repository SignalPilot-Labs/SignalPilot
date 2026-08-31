import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md("""# Title

    Some *markdown* text.""")
    return


@app.cell
def _():
    z = 1
    return


if __name__ == "__main__":
    app.run()
