import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot

    # Register globals
    sp.latex(filename=sp.notebook_dir() / "macros.tex")
    return (sp,)


@app.cell
def _(sp):
    sp.md(
        r"""
        $$
        c = \pm\root{a^2 + b^2}\in\RR
        $$
        """
    )
    return


@app.cell
def _(sp):
    sp.md(r"""$c = \pm\root{a^2 + b^2}\in\RR$""")
    return


if __name__ == "__main__":
    app.run()
