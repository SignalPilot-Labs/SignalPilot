import signalpilot

__generated_with = "0.3.8"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Pandas DataFrame: Extract values using regexp (regular expression)
        """
    )
    return


@app.cell
def __():
    import pandas as pd

    df = pd.DataFrame(
        {
            "request": ["GET /index.html?baz=3", "GET /foo.html?bar=1"],
        }
    )

    df["request"].str.extract(r"GET /([^?]+)\?", expand=True)
    return df, pd


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
