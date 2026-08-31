import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()

with app.setup:
    import math
    TAU = math.tau


@app.cell(hide_code=True)
def make_values():
    values = [TAU * i for i in range(10)]
    return (values,)


@app.function
def helper(v):
    return v * 2


@app.cell(column=2)
def _(values):
    total = sum(helper(v) for v in values)
    return (total,)


@app.cell
def _(sp, total):
    sp.md(f"""Total is {total}""")
    return


if __name__ == "__main__":
    app.run()
