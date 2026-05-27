# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "dask",
#     "vega-datasets",
#     "polars",
#     "altair",
#     "pyarrow",
#     "sp",
#     "pandas",
#     "ibis",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell(hide_code=True)
def _(sp):
    sp.md("""# 🤖 Lists/Dicts""")
    return


@app.cell
def _(sp):
    _data = [
        {"Name": "John", "Age": 30, "City": "New York"},
        {"Name": "Alice", "Age": 24, "City": "San Francisco"},
    ]
    as_list = sp.ui.table(_data)
    as_list
    return (as_list,)


@app.cell
def _(as_list):
    as_list.value
    return


@app.cell
def _(sp):
    _data = {
        "Name": ["John", "Alice"],
        "Age": [30, 24],
        "City": ["New York", "San Francisco"],
    }
    as_dict = sp.ui.table(_data)
    as_dict
    return (as_dict,)


@app.cell
def _(as_dict):
    as_dict.value
    return


@app.cell
def _(sp):
    _data = [1, 2, "hello", False]
    as_primitives = sp.ui.table(_data)
    as_primitives
    return (as_primitives,)


@app.cell
def _(as_primitives):
    as_primitives.value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""# 🐼 Pandas""")
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## sp.ui.dataframe""")
    return


@app.cell
def _(cars, sp):
    dataframe = sp.ui.dataframe(cars)
    dataframe
    return (dataframe,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## sp.ui.table""")
    return


@app.cell
def _(dataframe, sp):
    t = sp.ui.table(dataframe.value)
    t
    return (t,)


@app.cell
def _(t):
    t.value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## .value""")
    return


@app.cell
def _(dataframe):
    dataframe.value
    return


@app.cell
def _(dataframe):
    dataframe.value["Cylinders"]
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## sp.ui.data_explorer""")
    return


@app.cell
def _(sp, pl_dataframe):
    sp.ui.data_explorer(pl_dataframe)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""# 🐻‍❄️ Polars""")
    return


@app.cell
def _(sp):
    sp.md("""## sp.ui.dataframe""")
    return


@app.cell
def _(sp, pl_dataframe):
    pl_dataframe_prime = sp.ui.dataframe(pl_dataframe)
    pl_dataframe_prime
    return (pl_dataframe_prime,)


@app.cell
def _(pl_dataframe_prime):
    pl_dataframe_prime.value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## sp.ui.table""")
    return


@app.cell
def _(cars, sp, pl):
    pl_dataframe = pl.DataFrame(cars)
    sp.ui.table(pl_dataframe, selection=None)
    return (pl_dataframe,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## sp.ui.data_explorer""")
    return


@app.cell
def _(sp, pl_dataframe):
    sp.ui.data_explorer(pl_dataframe)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""# 🏹 Arrow""")
    return


@app.cell
def _(cars, sp, pa):
    arrow_table = pa.Table.from_pandas(cars)
    sp.accordion({"Details": sp.plain_text(arrow_table)})
    return (arrow_table,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## sp.ui.table""")
    return


@app.cell
def _(arrow_table, sp):
    arrow_table_el = sp.ui.table(arrow_table)
    arrow_table_el
    return (arrow_table_el,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## .value""")
    return


@app.cell
def _(arrow_table_el):
    arrow_table_el.value
    return


@app.cell
def _(arrow_table, sp):
    sp.ui.data_explorer(arrow_table)
    return


@app.cell
def _(sp):
    sp.md(
        rf"""
        # 💽 Dataframe protocol
        > See the [API](https://data-apis.org/dataframe-protocol/latest/API.html)
        """
    )
    return


@app.cell
def _():
    import dask.dataframe as dd
    import requests

    dask_df = dd.read_csv(
        "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/iris.csv"
    )
    dask_df
    return


@app.cell
def _():
    import ibis

    ibis.options.interactive = True

    ibis_data = ibis.read_csv(
        "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/penguins.csv",
        table_name="penguins",
    )
    ibis_data
    return (ibis_data,)


@app.cell
def _(sp):
    sp.md(rf"## sp.ui.table")
    return


@app.cell
def _(ibis_penguins):
    ibis_penguins.value
    return


@app.cell
def _(ibis_data, sp):
    ibis_penguins = sp.ui.table(ibis_data)
    ibis_penguins
    return (ibis_penguins,)


@app.cell
def _(ibis_penguins):
    ibis_penguins.value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(rf"## sp.ui.data_explorer")
    return


@app.cell
def _(ibis_data, sp):
    sp.ui.data_explorer(ibis_data)
    return


@app.cell
def _():
    import signalpilot
    import pandas as pd
    import polars as pl
    import pyarrow as pa
    import vega_datasets
    import altair as alt

    cars = vega_datasets.data.cars()
    return cars, sp, pa, pl


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM cars WHERE Cylinders > 6;
        """
    )
    return


if __name__ == "__main__":
    app.run()
