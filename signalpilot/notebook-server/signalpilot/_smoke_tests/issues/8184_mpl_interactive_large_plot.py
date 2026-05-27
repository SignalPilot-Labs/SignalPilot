import signalpilot

__generated_with = "0.19.11"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import matplotlib.pyplot as plt
    import numpy as np

    return sp, np, plt


@app.cell
def _(sp, np, plt):
    # n=200 should work
    plt.figure()
    plt.imshow(np.random.random([200, 200]))
    sp.mpl.interactive(plt.gca())
    return


@app.cell
def _(sp, np, plt):
    # n=300 was blank before fix (GH-8184)
    plt.figure()
    plt.imshow(np.random.random([300, 300]))
    sp.mpl.interactive(plt.gca())
    return


@app.cell
def _(sp, np, plt):
    # n=500 stress test
    plt.figure()
    plt.imshow(np.random.random([500, 500]))
    sp.mpl.interactive(plt.gca())
    return


if __name__ == "__main__":
    app.run()
