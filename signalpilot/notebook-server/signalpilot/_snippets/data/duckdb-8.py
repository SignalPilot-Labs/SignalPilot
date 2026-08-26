
import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: Parquet File Ingestion

        This snippet demonstrates how to query Parquet files directly using DuckDB.
        """
    )
    return


@app.cell
def _():
    parquet_path = 'sample-file.parquet'
    return (parquet_path,)


@app.cell
def _(sp, parquet_path):
    query = sp.sql(
        f"""
        SELECT * FROM read_parquet('{parquet_path}')
        LIMIT 10
        """
    )
    return (query,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
