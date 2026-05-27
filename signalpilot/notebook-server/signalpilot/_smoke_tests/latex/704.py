import signalpilot

__generated_with = "0.19.6"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    # Incrementing functions
    Bug from [#704](https://docs.signalpilot.ai/docs/)
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    \begin{align}
        B' &=-\nabla \times E,\\
        E' &=\nabla \times B - 4\pi j\\
        e^{\pi i} + 1 = 0
    \end{align}
    """)
    return


if __name__ == "__main__":
    app.run()
