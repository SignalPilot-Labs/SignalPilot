import signalpilot

__generated_with = "0.16.5"
app = sp.App(width="medium")


@app.cell
def _():
    FILE = "https://data.source.coop/cholmes/eurocrops/unprojected/geoparquet/FR_2018_EC21.parquet"
    return (FILE,)


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        INSTALL spatial;
        LOAD spatial;
        """
    )
    return


@app.cell
def _():
    10
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT 1;
        """
    )
    return


@app.cell
def _(FILE, sp, null):
    _df = sp.sql(
        f"""
        CREATE TABLE gdf AS
        SELECT * 
        FROM '{FILE}'
        """
    )
    return


if __name__ == "__main__":
    app.run()
