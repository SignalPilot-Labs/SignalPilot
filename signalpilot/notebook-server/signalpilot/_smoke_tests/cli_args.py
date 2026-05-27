# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
# ]
# ///
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _(sp):
    sp.md(
        """
        Re-run this with notebook with the following command line:

        ```bash
        sp edit sp/_smoke_tests/cli_args.py -- -a foo --b=bar -d 10 -d 20 -d false
        ```
        """
    )
    return


@app.cell
def _(sp):
    sp.cli_args().to_dict()
    return


if __name__ == "__main__":
    app.run()
