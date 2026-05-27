# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _(sp):
    sp.md(
        r"""
        $$
        \begin{align*}
        x &= 1 && \tag{Taylor} \\
        x &= 1123123123123123 && \tag{Taylor's rule} \\
        \end{align*}
        $$
        """
    )
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
