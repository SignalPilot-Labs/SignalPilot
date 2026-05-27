# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _(sp):
    query_params = sp.query_params()
    return (query_params,)


@app.cell
def _(sp, query_params):
    # In another cell
    search = sp.ui.text(
        value=query_params["search"] or "",
        on_change=lambda v: query_params.set("search", v),
    )
    search
    return


@app.cell
def _(sp):
    toggle = sp.ui.switch(label="Toggle me")
    toggle
    return (toggle,)


@app.cell
def _(query_params, toggle):
    # change the value of a query param, and watch the next cell run automatically
    query_params["has_run"] = toggle.value
    return


@app.cell
def _(sp):
    new_value = sp.ui.text(label="Text to add")
    return (new_value,)


@app.cell
def _(sp, new_value, query_params):
    append_button = sp.ui.button(
        label="Add to query param",
        on_click=lambda _: query_params.append("list", new_value.value),
    )
    replace_button = sp.ui.button(
        label="Replace in query param",
        on_click=lambda _: query_params.set("list", new_value.value),
    )
    sp.hstack([new_value, append_button, replace_button])
    return


@app.cell
def _(sp, query_params):
    items = [
        {"key": key, "value": str(value)}
        for key, value in query_params.to_dict().items()
    ]
    sp.ui.table(items, selection=None, label="Query params")
    return


@app.cell
def _(sp):
    sp.md("""You can also initialized with query params. Open this URL [/?foo=1&bar=2&bar=3&baz=4](/?foo=1&bar=2&bar=3&baz=4) and restart the kernel""")
    return


@app.cell
def _():
    import signalpilot
    import random
    return (sp,)


if __name__ == "__main__":
    app.run()
