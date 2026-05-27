# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Smoke test for stale <img> rendering when sp.Html re-runs with new src URLs.
#
# Repro: pick a set, run the cell, then change the radio to swap the
# URLs. Each <img> should display the newly selected image. Before the
# RenderHTML key-by-src fix, the prior images stayed painted.

import signalpilot

__generated_with = "0.23.5"
app = sp.App()


@app.cell
def _():
    import signalpilot

    return (sp,)


@app.cell
def _(sp):
    sets = {
        "set A (cats)": [
            "https://placecats.com/200/200",
            "https://placecats.com/201/200",
            "https://placecats.com/202/200",
            "https://placecats.com/203/200",
            "https://placecats.com/204/200",
        ],
        "set B (bears)": [
            "https://placebear.com/200/200",
            "https://placebear.com/201/200",
            "https://placebear.com/202/200",
            "https://placebear.com/203/200",
            "https://placebear.com/204/200",
        ],
    }
    choice = sp.ui.radio(options=list(sets), value="set A (cats)")
    choice
    return choice, sets


@app.cell
def _(choice, sp, sets):
    urls = sets[choice.value]
    imgs = "".join(
        f'<img src="{u}" width="120" height="120" style="margin:4px"/>'
        for u in urls
    )
    sp.Html(f'<div>{imgs}</div>')
    return


@app.cell
def _(sp):
    sp.md("""
    ### What to check
    - Toggle the radio between the two sets repeatedly.
    - Each `<img>` should swap to the newly selected URL.
    - Open devtools and confirm the rendered `<img>` `src` attributes
      match the selected set, and that the painted images match too.
    """)
    return


if __name__ == "__main__":
    app.run()
