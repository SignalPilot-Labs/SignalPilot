# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
#     "altair",
#     "vega-datasets",
#     "geopandas",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    import altair as alt
    import geopandas as gpd
    from vega_datasets import data

    url = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"
    gdf_ne = gpd.read_file(url)  # zipped shapefile
    gdf_ne = gdf_ne[["NAME", "CONTINENT", "POP_EST", "geometry"]]
    return alt, gdf_ne


@app.cell
def _(gdf_ne):
    gdf_sel = gdf_ne.query("CONTINENT == 'Africa'")
    return (gdf_sel,)


@app.cell
def _(alt, gdf_sel):
    chart = (
        alt.Chart(gdf_sel)
        .mark_geoshape(stroke="white", strokeWidth=1.5)
        .encode(fill="NAME:N")
    )
    return (chart,)


@app.cell
def _(chart):
    chart
    return


@app.cell
def _(chart):
    chart.mark.type
    return


@app.cell
def _(chart, sp):
    mo_chart = sp.ui.altair_chart(chart)
    mo_chart
    return (mo_chart,)


@app.cell
def _(sp, mo_chart):
    sp.ui.table(mo_chart.value)
    return


@app.cell
def _(chart, sp):
    sp.ui.altair_chart(chart, chart_selection=None)
    return


if __name__ == "__main__":
    app.run()
