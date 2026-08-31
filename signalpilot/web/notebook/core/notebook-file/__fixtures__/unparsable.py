import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell
def _():
    x = 1
    return


app._unparsable_cell(
    r"""
    this is not ( valid python
    """,
    name="broken"
)


if __name__ == "__main__":
    app.run()
