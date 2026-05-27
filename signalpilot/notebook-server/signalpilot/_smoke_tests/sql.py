# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "duckdb",
#     "vega-datasets",
#     "sp",
#     "altair",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import altair as alt
    from vega_datasets import data
    import duckdb
    import signalpilot
    return alt, data, duckdb, mo


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## Cars""")
    return


@app.cell
def _(data, sp):
    # Create a slider with the range of car cylinders
    cars = data.cars()
    cylinders = sp.ui.slider.from_series(cars["Cylinders"])
    cylinders
    return (cylinders,)


@app.cell
def _(cylinders, sp):
    df = sp.sql(
        f"""
        SELECT "Name", "Miles_per_Gallon", "Cylinders", "Horsepower"
        FROM cars
        WHERE "Cylinders" = {cylinders.value}
        """
    )
    return (df,)


@app.cell
def _(alt, df, sp):
    # Chart the filtered cars
    sp.ui.altair_chart(
        alt.Chart(df)
        .mark_point()
        .encode(x="Miles_per_Gallon", y="Horsepower")
        .properties(height=200)
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""## Airports""")
    return


@app.cell
def _(data):
    airports = data.airports()
    return


@app.cell
def _(sp):
    less_airports = sp.sql(
        f"""
        select * from airports limit 2
        """
    )
    return (less_airports,)


@app.cell
def _(less_airports):
    len(less_airports)
    return


@app.cell
def _(sp):
    sp.md("""## Google Sheets""")
    return


@app.cell
def _():
    sheet = "https://docs.google.com/spreadsheets/export?format=csv&id=1GuEPkwjdICgJ31Ji3iUoarirZNDbPxQj_kf7fd4h4Ro"
    return (sheet,)


@app.cell
def _(sp, sheet):
    job_types = sp.sql(
        f"""
        SELECT DISTINCT current_job_title
        FROM read_csv_auto('{sheet}', normalize_names=True)
        """
    )
    return (job_types,)


@app.cell
def _(job_types, sp):
    job_title = sp.ui.dropdown.from_series(job_types["current_job_title"])
    job_title
    return (job_title,)


@app.cell
def _(job_title, sp, sheet):
    _df = sp.sql(
        f"""
        SELECT *
        FROM read_csv_auto('{sheet}', normalize_names=True)
        WHERE current_job_title == '{job_title.value}'
        """
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""Debug""")
    return


@app.cell(hide_code=True)
def _(duckdb):
    duckdb.get_table_names(
        f"""
        SELECT "Name", "Miles_per_Gallon", "Cylinders", "Horsepower"
        FROM cars
        """
    )
    return


@app.cell(hide_code=True)
def _(duckdb, job_title, sheet):
    duckdb.get_table_names(
        f"""
        SELECT *
        FROM read_csv_auto('{sheet}', normalize_names=True)
        WHERE current_job_title == '{job_title.value}'
        """
    )
    return


@app.cell
def _(sp):
    grouped_cars_by_origin = sp.sql(
        f"""
        SELECT "Origin", COUNT(*) AS "Count"
        FROM cars
        GROUP BY "Origin"
        LIMIT 100
        """
    )
    return


if __name__ == "__main__":
    app.run()
