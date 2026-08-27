import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App()


@app.cell
def strings():
    s = """
    @app.cell
    def _():
        return
    """
    t = '''
    with app.setup:
        pass
    if __name__ == "__main__":
        app.run()
    '''
    return s, t


@app.cell
def _(s, t):
    combined = s + t
    print(combined)
    return


if __name__ == "__main__":
    app.run()
