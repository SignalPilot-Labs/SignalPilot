# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # DuckDB: JSON File Ingestion

        This snippet demonstrates how to query JSON files directly using DuckDB.
        """
    )
    return


@app.cell
def _():
    json_path = 'sample-file.json'
    return (json_path,)


@app.cell
def _(json_path, sp):
    query = sp.sql(
        f"""
        SELECT * FROM read_json_auto('{json_path}')
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
