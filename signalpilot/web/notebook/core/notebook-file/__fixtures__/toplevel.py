import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.function
def add(a, b):
    return a + b


@app.class_definition
class Point:
    def __init__(self, x):
        self.x = x


@app.cell
def _():
    result = add(1, 2)
    return


if __name__ == "__main__":
    app.run()
