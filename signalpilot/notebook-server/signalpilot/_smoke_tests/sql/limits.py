# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md(r"""## Small table""")
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        CREATE OR REPLACE TABLE small_table AS SELECT * FROM range(1000)
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM small_table;
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM small_table LIMIT 10;
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM small_table LIMIT 1000;
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM small_table LIMIT 300;
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM small_table LIMIT 301;
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM small_table LIMIT 1100;
        """
    )
    return


@app.cell
def _(sp):
    sp.md(r"""## Large table""")
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        CREATE OR REPLACE TABLE large_table AS SELECT * FROM range(30_000);
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM large_table;
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM large_table LIMIT 25_000;
        """
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM large_table LIMIT 20_000;
        """
    )
    return


if __name__ == "__main__":
    app.run()
