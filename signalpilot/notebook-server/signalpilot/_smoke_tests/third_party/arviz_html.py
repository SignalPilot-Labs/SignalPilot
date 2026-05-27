import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return


@app.cell
def _():
    import arviz as az

    centered_data = az.load_arviz_data("centered_eight")
    centered_data
    return


if __name__ == "__main__":
    app.run()
