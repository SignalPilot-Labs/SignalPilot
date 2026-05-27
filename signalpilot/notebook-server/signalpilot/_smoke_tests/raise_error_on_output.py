
import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.class_definition
class Mischief:
    def _mime_(self):
        raise ValueError("error!")


@app.cell
def _():
    mischief = Mischief()
    return (mischief,)


@app.cell
def _(mischief):
    mischief
    return


if __name__ == "__main__":
    app.run()
