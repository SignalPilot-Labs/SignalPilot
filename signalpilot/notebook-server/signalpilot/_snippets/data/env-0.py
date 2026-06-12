import signalpilot

__generated_with = "0.11.0"
app = sp.App(width="medium")


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""# Load .env""")
    return


@app.cell
def _():
    import dotenv

    dotenv.load_dotenv(dotenv.find_dotenv(usecwd=True))
    return (dotenv,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
