import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell
def _():
    x = 1
    import textwrap

    return textwrap, x


@app.cell
def _(textwrap, x):
    print(textwrap.dedent('  hi'), x)
    return


if __name__ == "__main__":
    app.run()
