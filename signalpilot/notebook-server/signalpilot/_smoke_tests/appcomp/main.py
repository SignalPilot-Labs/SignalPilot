
import signalpilot

__generated_with = "0.18.4"
app = sp.App(width="medium")


@app.cell
def _():
    from inner import app
    return (app,)


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Render the same app multiple times
    """)
    return


@app.cell
async def _(app):
    result = await app.embed()
    result.output
    return (result,)


@app.cell
def _(result):
    result.defs["x"].value
    return


@app.cell
def _(result):
    result.defs["y"].value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Clone an app
    """)
    return


@app.cell
def _(app):
    clone = app.clone()
    return (clone,)


@app.cell
async def _(clone):
    clone_result = await clone.embed()
    clone_result.output
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Parametrize an app
    """)
    return


@app.cell
def _(app):
    parametrized_app = app.clone()
    return (parametrized_app,)


@app.cell
async def _(parametrized_app):
    _result = await parametrized_app.embed(defs={"x_initial_value": 0})
    _result.output
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Render an app inside tabs
    """)
    return


@app.cell
async def _(app, sp):
    tabs = sp.ui.tabs({"🧮": (await app.embed()).output, "📝": sp.md("Hello world")})
    tabs
    return


@app.cell
def _(sp):
    sp.md(rf"""
    ## Render an app that uses function calls
    """)
    return


@app.cell
def _():
    from make_table import app as table_app
    return (table_app,)


@app.cell
async def _(table_app):
    table_app_results = await table_app.embed()
    return (table_app_results,)


@app.cell
def _(table_app_results):
    table_app_results.output
    return


@app.cell
def _(table_app_results):
    table_app_results.defs
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
