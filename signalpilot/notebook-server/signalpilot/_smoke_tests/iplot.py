
import signalpilot

__generated_with = "0.20.4"
app = sp.App()


@app.cell
def _():
    # sp.app_meta().request
    return


@app.cell
def _():
    import signalpilot
    import numpy as np
    import matplotlib.pyplot as plt

    return sp, np, plt


@app.cell
def _(sp, np, plt):
    def interactive_plot(seed=42, size=100):
        # Generating random data
        np.random.seed(seed)
        x = np.random.randint(0, 100, size=size)
        y = np.random.randint(0, 100, size=size)
        z = np.random.randint(0, 100, size=size)

        # Creating a 3D scatter plot
        fig = plt.figure()
        ax = fig.add_subplot(111, projection="3d")
        ax.scatter(x, y, z, c="r", marker="o")

        ax.set_xlabel("X Label")
        ax.set_ylabel("Y Label")
        ax.set_zlabel("Z Label")

        return sp.mpl.interactive(fig)

    return (interactive_plot,)


@app.cell
def _(interactive_plot):
    interactive_plot(size=10)
    return


@app.cell
def _(interactive_plot):
    b = interactive_plot(size=20)
    b
    return


@app.cell
def _(sp, plt):
    plt.plot([1, 2])
    sp.mpl.interactive(plt.gca())
    return


@app.cell
def _(plt):
    plt.plot([3, 4])
    return


if __name__ == "__main__":
    app.run()
