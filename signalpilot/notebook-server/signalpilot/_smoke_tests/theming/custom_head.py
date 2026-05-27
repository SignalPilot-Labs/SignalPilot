# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "vega-datasets",
#     "sp",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium", html_head_file="head.html")


@app.cell
def _():
    import signalpilot
    from vega_datasets import data
    return data, mo


@app.cell
def _(data):
    data.cars()
    return


@app.cell
def _(sp):
    sp.callout(
        sp.md("""
    ## Callout

    This font should be styled
    """)
    )
    return


@app.cell
def _(sp):
    sp.md(
        r"""
        # heading

        Here is a paragraph
        """
    )
    return


if __name__ == "__main__":
    app.run()
