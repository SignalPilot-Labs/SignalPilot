import signalpilot

__generated_with = "0.19.10"
app = sp.App()


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    hello $$f(x) = y$$ world
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    hello
    $$f(x) = y$$
    world
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    hello $$this is not latex

    $$ this is still not latex
    """)
    return


@app.cell
def _():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
