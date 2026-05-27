# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "altair",
#     "sp",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import altair as alt

    alt.themes
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
