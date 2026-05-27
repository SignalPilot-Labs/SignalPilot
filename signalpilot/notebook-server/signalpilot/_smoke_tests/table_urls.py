# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.ui.table(
        [
            {
                "title": "New York",
                "url": "https://en.wikipedia.org/wiki/New_York_City",
            },
            {
                "title": "London",
                "url": "https://en.wikipedia.org/wiki/London",
            },
            {
                "title": "Paris",
                "url": "https://en.wikipedia.org/wiki/Paris",
            },
        ],
    )
    return


if __name__ == "__main__":
    app.run()
