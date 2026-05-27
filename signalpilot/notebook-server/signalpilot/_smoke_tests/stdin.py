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
def _():
    value = input("what is your name?")
    return (value,)


@app.cell
def _(sp, value):
    sp.md(f"## 👋 Hi {value}")
    return


@app.cell
def _():
    print('hi')
    return


@app.cell
def _():
    print('there')
    return


if __name__ == "__main__":
    app.run()
