import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM my_table
        """
    )
    [sp.refs(), sp.defs()]
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM my_view
        """
    )
    [sp.refs(), sp.defs()]
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        CREATE OR REPlACE TABLE my_table (a text);
        INSERT INTO my_table (VALUES ('foo'), ('bar'));
        """
    )
    [sp.refs(), sp.defs()]
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        CREATE OR REPLACE VIEW my_view AS (SELECT * FROM my_table WHERE a LIKE 'f%o')
        """
    )
    [sp.refs(), sp.defs()]
    return


@app.cell(hide_code=True)
def _():
    import signalpilot
    import pandas as pd
    return (sp,)


if __name__ == "__main__":
    app.run()
