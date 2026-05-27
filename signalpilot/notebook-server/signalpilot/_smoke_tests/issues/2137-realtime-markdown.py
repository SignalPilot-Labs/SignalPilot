import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import time
    return sp, time


@app.cell
def _(time):
    time.sleep(10)
    return


@app.cell
def _(sp):
    sp.md(
        r"""
        ### Realtime Markdown Editing
        Everything you type should update the cell output in realtime, which is pretty cool!

        | Feature           | Description                                            |
        |-------------------|--------------------------------------------------------|
        | Compact Size      | Small and versatile for display in various containers. |
        | Easy Maintenance  | Requires minimal care and indirect sunlight.           |
        | Unique Appearance | Spherical and soft, visually distinct.                 |
        | Oxygen Production | Helps oxygenate aquatic environments.                  |
        | Slow Growth       | Grows about 5 mm per year, keeping size manageable.    |
        | Longevity         | Can live for many years, even over a century.          |
        | Cultural Symbol   | In Japan, seen as good luck charms.                    |
        | Adaptable         | Thrives in various water conditions.                   |
        | Non-Invasive      | Won't overtake the environment like other plants.      |
        | Eco-Friendly      | Sustainable and environmentally safe.                  |

        ![](https://docs.signalpilot.ai/docs/)
        """
    )
    return


if __name__ == "__main__":
    app.run()
