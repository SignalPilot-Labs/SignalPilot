import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()

with app.setup:
    import json
    CONST = 42


@app.cell
def _():
    data = json.dumps({'v': CONST})
    return


if __name__ == "__main__":
    app.run()
