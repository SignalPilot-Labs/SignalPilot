# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.sidebar(
        [
            sp.md("# sp"),
            sp.nav_menu(
                {
                    "#/home": f"{sp.icon('lucide:home')} Home",
                    "#/about": f"{sp.icon('lucide:user')} About",
                    "#/sales": f"{sp.icon('lucide:bar-chart')} Sales",
                },
                orientation="vertical",
            ),
        ]
    )
    return


@app.cell
def _(sp):
    def render_home():
        return sp.md("""
         <p align="center">
          <img src="https://docs.signalpilot.ai/docs/">
        </p>

        <p align="center">
          <em>A reactive Python notebook that's reproducible, git-friendly, and deployable as scripts or apps.</em>

        <p align="center">
          <a href="https://docs.signalpilot.ai/docs/" target="_blank"><strong>Docs</strong></a> ·
          <a href="https://docs.signalpilot.ai/docs/" target="_blank"><strong>Discord</strong></a> ·
          <a href="https://docs.signalpilot.ai/docs/" target="_blank"><strong>Examples</strong></a>
        </p>

        <p align="center">
        <a href="https://docs.signalpilot.ai/docs/"><img src="https://img.shields.io/pypi/v/signalpilot?color=%2334D058&label=pypi" /></a>
        <a href="https://anaconda.org/conda-forge/signalpilot"/img><img src="https://img.shields.io/conda/vn/conda-forge/signalpilot.svg"></img></a>
        <a href="https://docs.signalpilot.ai/docs/"><img src="https://img.shields.io/pypi/l/signalpilot"></img></a>
        </p>

        """)
    return (render_home,)


@app.cell
def _(sp):
    def render_about():
        return sp.md(
            """
        # About

        **sp** is a reactive Python notebook: run a cell or interact with a UI
        element, and sp automatically runs dependent cells, keeping code and outputs
        consistent. sp notebooks are stored as pure Python, executable as scripts,
        and deployable as apps.

        **Highlights**.

        - **reactive**: run a cell, and sp automatically runs all dependent cells
        - **interactive**: bind sliders, tables, plots, and more to Python — no callbacks required
        - **reproducible**: no hidden state, deterministic execution
        - **executable**: execute as a Python script, parameterized by CLI args
        - **shareable**: deploy as an interactive web app, or run in the browser via WASM
        - **git-friendly**: stored as `.py` files


        ## Community

        We're building a community. Come hang out with us!

        - 🌟 [Star us on GitHub](https://docs.signalpilot.ai/docs/)
        - 💬 [Chat with us on Discord](https://docs.signalpilot.ai/docs/)
        - 📧 [Subscribe to our Newsletter](https://docs.signalpilot.ai/docs/)
        - ☁️ [Join our Cloud Waitlist](https://docs.signalpilot.ai/docs/)
        - ✏️ [Start a GitHub Discussion](https://docs.signalpilot.ai/docs/)
        - 🐦 [Follow us on Twitter](https://twitter.com/signalpilot_io)
        - 🕴️ [Follow us on LinkedIn](https://www.linkedin.com/company/signalpilot-io)

        """
        )
    return (render_about,)


@app.cell
def _(sp):
    slider = sp.ui.slider(0, 100, value=20)
    return (slider,)


@app.cell
def _(sp, slider):
    def render_sales():
        import altair as alt
        import pandas as pd
        import numpy as np

        num = slider.value
        x = np.arange(num)
        y = np.random.randint(0, 100, num)
        df = pd.DataFrame({"x": x, "y": y})

        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x="x",
                y="y",
            )
        )

        return sp.md(
            f"""
        # Sales

        Number of points: {slider}

        {sp.as_html(sp.ui.altair_chart(chart))}
        """
        )
    return (render_sales,)


@app.cell
def _(sp, render_about, render_home, render_sales):
    sp.routes(
        {
            "#/home": render_home,
            "#/about": render_about,
            "#/sales": render_sales,
            sp.routes.CATCH_ALL: render_home,
        }
    )
    return


if __name__ == "__main__":
    app.run()
