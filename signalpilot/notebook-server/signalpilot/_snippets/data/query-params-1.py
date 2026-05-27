
import signalpilot

__generated_with = "0.4.0"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Query Parameters: Writing to query parameters

        You can also use `sp.query_params` to set query parameters in order
        to keep track of state in the URL. This is useful for bookmarking
        or sharing a particular state of the notebook while running as an
        application with `sp run`.
        """
    )
    return


@app.cell
def __(sp):
    query_params = sp.query_params()
    return query_params,


@app.cell
def __(mo, query_params):
    slider = sp.ui.slider(
        0,
        10,
        value=query_params.get("slider") or 1,
        on_change=lambda x: query_params.set("slider", x),
    )
    slider
    return slider,


@app.cell
def __(mo, query_params):
    search = sp.ui.text(
        value=query_params.get("search") or "",
        on_change=lambda x: query_params.set("search", x),
    )
    search
    return search,


@app.cell
def __():
    import signalpilot
    return sp,


if __name__ == "__main__":
    app.run()
