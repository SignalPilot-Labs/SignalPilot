import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md(r"""
        Importa recordar as seguintes regras de diferenciação de matrizes:

        $$\frac{\partial\, u'v}{\partial\, v} = \frac{\partial\, v'u}{\partial\, v} = u$$

        sendo $u$ e $v$ dois vetores.

        $$\frac{\partial\, v'Av}{\partial\, v}=2Av=2v'A$$

        em que $A$ é uma matriz simétrica. No nosso caso, $A=X'X$ e $v=\hat{\boldsymbol{\beta}}$.
    """).center().callout()
    return


@app.cell
def _(sp):
    sp.md(
        r"""
        !!! tip ""

            Importa recordar as seguintes regras de diferenciação de matrizes:

            $$\frac{\partial\, u'v}{\partial\, v} = \frac{\partial\, v'u}{\partial\, v} = u$$

            sendo $u$ e $v$ dois vetores.

            $$\frac{\partial\, v'Av}{\partial\, v}=2Av=2v'A$$

            em que $A$ é uma matriz simétrica. No nosso caso, $A=X'X$ e $v=\hat{\boldsymbol{\beta}}$.
        """
    )
    return


@app.cell
def _(sp):
    sp.accordion(
        {
            "Tip": sp.md(r"""
        Importa recordar as seguintes regras de diferenciação de matrizes:

        $$\frac{\partial\, u'v}{\partial\, v} = \frac{\partial\, v'u}{\partial\, v} = u$$

        sendo $u$ e $v$ dois vetores.

        $$\frac{\partial\, v'Av}{\partial\, v}=2Av=2v'A$$

        em que $A$ é uma matriz simétrica. No nosso caso, $A=X'X$ e $v=\hat{\boldsymbol{\beta}}$.
    """).center()
        }
    )
    return


if __name__ == "__main__":
    app.run()
