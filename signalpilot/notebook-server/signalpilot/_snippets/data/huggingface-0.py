# Copyright 2026 SignalPilot. All rights reserved.
import signalpilot

__generated_with = "0.11.0"
app = sp.App(width="medium")


@app.cell(hide_code=True)
def _(sp):
    sp.md(
        r"""
        # Hugging Face: Datasets with Polars

        Fetch any datasets from [Hugging Face Datasets](https://huggingface.co/datasets) with [Polars](https://www.pola.rs/).
        """
    )
    return


@app.cell
def _():
    import polars as pl
    return (pl,)


@app.cell
def _(pl):
    df = pl.read_csv("hf://datasets/scikit-learn/Fish/Fish.csv")
    df
    return (df,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
