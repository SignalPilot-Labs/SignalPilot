import signalpilot

__generated_with = "0.11.0"
app = sp.App(width="medium")


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        r"""
        # Hugging Face: Datasets with SQL

        Fetch any datasets from [Hugging Face Datasets](https://huggingface.co/datasets) with SQL via [DuckDB](https://duckdb.org/)
        """
    )
    return


@app.cell
def _():
    import duckdb
    import polars as pl
    return duckdb, pl


@app.cell
def _(sp):
    data = sp.sql(
        f"""
        SELECT * FROM "hf://datasets/scikit-learn/Fish/Fish.csv"
        """
    )
    return (data,)


@app.cell
def _(data):
    # Get the SQL result back in Python
    data.describe()
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
