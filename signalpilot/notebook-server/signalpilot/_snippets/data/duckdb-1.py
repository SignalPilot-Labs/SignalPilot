# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: CSV File Ingestion

        This snippet demonstrates how to query CSV files directly using DuckDB.
        """
    )
    return


@app.cell
def _():
    csv_path = 'sample-file.csv'
    return (csv_path,)


@app.cell
def _(csv_path, sp):
    query = sp.sql(
        f"""
        SELECT * FROM read_csv('{csv_path}', AUTO_DETECT=TRUE)
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
