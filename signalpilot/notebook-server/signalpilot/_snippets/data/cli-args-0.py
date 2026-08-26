
import signalpilot

__generated_with = "0.4.0"
app = sp.App()


@app.cell
def __(sp):
    sp.md(
        r"""
        # CLI Arguments: Reading CLI arguments

        Use `sp.cli_args` to access command line arguments passed to the notebook.
        For example, you can pass arguments to the notebook when running it as an
        application with `sp run`.

        ```bash
        sp run app.py -- --arg1 value1 --arg2 value2
        ```
        """
    )
    return


@app.cell
def __(sp):
    params = sp.cli_args()
    params
    return params,


@app.cell
def __():
    import signalpilot
    return sp,


if __name__ == "__main__":
    app.run()
