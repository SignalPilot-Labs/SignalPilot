
import signalpilot

__generated_with = "0.11.0"
app = sp.App()


@app.cell
def _(sp):
    sp.md(
        r"""
        # Matplotlib: Heatmaps with Colormaps

        Create heatmaps using `imshow()` with custom colormaps.
        Common for visualizing matrices, correlations, and grid data.
        """
    )
    return


@app.cell
def _():
    import matplotlib.pyplot as plt
    import numpy as np
    return np, plt


@app.cell
def _(np, plt):
    def create_heatmap():
        # Create sample correlation matrix
        np.random.seed(42)
        data = np.random.randn(5, 5)
        corr = np.corrcoef(data)

        # Create heatmap
        fig, ax = plt.subplots(figsize=(7, 6))
        im = ax.imshow(corr, cmap='coolwarm', vmin=-1, vmax=1)

        # Add colorbar
        plt.colorbar(im)

        # Add labels
        ax.set_xticks(range(5))
        ax.set_yticks(range(5))
        ax.set_title('Correlation Matrix')

        return ax

    create_heatmap()
    return (create_heatmap,)


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
