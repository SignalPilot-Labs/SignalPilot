
import signalpilot

__generated_with = "0.4.0"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # Query Parameters: Reading query parameters

        Use `sp.query_params` to access query parameters passed to the notebook.
        """
    )
    return


@app.cell
def __(sp):
    params = sp.query_params()
    print(params)
    return (params,)


@app.cell
def __():
    import signalpilot

    return (sp,)


if __name__ == "__main__":
    app.run()
