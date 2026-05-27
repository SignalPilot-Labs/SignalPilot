# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "sp",
#     "numpy==2.2.3",
#     "treescope==0.1.9",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import treescope
    import numpy as np

    my_array = np.cos(np.arange(300).reshape((10,30)) * 0.2)
    figure = treescope.render_array(my_array)
    sp.iframe(figure._repr_html_())
    return (figure,)


@app.cell
def _(figure):
    figure
    return


if __name__ == "__main__":
    app.run()
