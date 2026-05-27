
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _(sp):
    sp.md("""Markdown""")
    return


@app.cell
def _(sp):
    sp.md(r"""Markdown with an escaped \"""quote\"""!!""")
    return


@app.cell
def _(sp):
    sp.md(
        """
        Markdown with a trailing "quote"
        """
    )
    return


@app.cell
def _(sp):
    sp.md(
        """
        "Markdown" with a leading quote
        """
    )
    return


@app.cell
def _(sp):
    sp.md("""Markdown with a trailing 'single quote'""")
    return


@app.cell
def _(sp):
    sp.md("""'Markdown' with a leading single quote""")
    return


@app.cell
def _(sp):
    sp.md("""Markdown with an triple-single '''quote'''!!""")
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
