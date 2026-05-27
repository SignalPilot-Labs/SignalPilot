import signalpilot

__generated_with = "0.20.4"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    from decimal import Decimal

    return Decimal, mo


@app.cell
def _(Decimal, sp, pd):
    import polars as pl

    _data = {
        "product": ["Apple", "Banana", "Cherry", "Date"],
        "price": pl.Series(
            [
                Decimal("1.99"),
                Decimal("0.50"),
                Decimal("3.25"),
                Decimal("0.00"),
            ],
            dtype=pl.Decimal(18, 2),
        ),
        "tax": pl.Series(
            [
                Decimal("1.123456789012345678"),
                Decimal("2.987654321098765432"),
                Decimal("1.123456789012345678"),
                Decimal("-3.492354321098723632"),
            ],
            dtype=pl.Decimal(36, 18),
        ),
        "quantity": [10, 5, 8, 3],
    }

    df = pl.DataFrame(_data)
    pl_table = sp.ui.table(df, label="Polars table with decimal values")
    pd_table = sp.ui.table(
        pd.DataFrame(_data), label="Pandas table with decimal values"
    )
    sp.vstack([pl_table, pd_table])
    return


@app.cell
def _(Decimal):
    import pandas as pd

    pandas_decimal_data = pd.DataFrame(
        {"decimals": [Decimal(i) / Decimal("100") for i in range(201)]}
    )
    pandas_decimal_data
    return (pd,)


if __name__ == "__main__":
    app.run()
