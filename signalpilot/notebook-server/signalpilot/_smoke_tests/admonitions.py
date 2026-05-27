# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.19.6"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    kinds = [
        # ---
        "note",
        # ---
        "danger",
        "error",
        "caution",
        # ---
        "hint",
        # ---
        "important",
        # ---
        "tip",
        # ---
        "attention",
        "warning",
    ]


    def create(kind):
        return sp.md(
            f"""
    /// {kind} | {kind} admonition
    This is an admonition for {kind}
    ///
            """
        )


    sp.vstack([create(kind) for kind in kinds])
    return


@app.cell
def _(sp):
    sp.md("""
    # Misc
    """)
    return


@app.cell
def _(sp):
    sp.md("""
    /// important |
    This is an admonition box without a title.
    ///
    """)
    return


@app.cell
def _(sp):
    sp.md(r"""
    /// tip |
    Importa recordar as seguintes regras de diferenciação de matrizes:

    $$\frac{\partial\, u'v}{\partial\, v} = \frac{\partial\, v'u}{\partial\, v} = u$$

    sendo $u$ e $v$ dois vetores.

    $$\frac{\partial\, v'Av}{\partial\, v}=2Av=2v'A$$

    em que $A$ é uma matriz simétrica. No nosso caso, $A=X'X$ e $v=\hat{\boldsymbol{\beta}}$.
    ///
    """)
    return


if __name__ == "__main__":
    app.run()
