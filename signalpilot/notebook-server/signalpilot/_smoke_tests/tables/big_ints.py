import signalpilot

__generated_with = "0.17.6"
app = sp.App(width="medium")


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Big Ints
    """)
    return


@app.cell(hide_code=True)
def _():
    data = {
        "int": [1, 2, 3],
        "bigint_1": [
            1000000000000000000,
            1000000000000000001,
            1000000000000000002,
        ],
        "bigint_2": [
            2000000000000000000,
            2000000000000000001,
            2000000000000000002,
        ],
        "bigint_3": [
            3000000000000000000,
            3000000000000000001,
            3000000000000000002,
        ],
    }
    return (data,)


@app.cell
def _(data, sp):
    import pandas as pd

    sp.vstack([sp.plain(pd.DataFrame(data)), pd.DataFrame(data)])
    return


@app.cell
def _(data, sp):
    import polars as pl

    sp.vstack([sp.plain(pl.DataFrame(data)), pl.DataFrame(data)])
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
