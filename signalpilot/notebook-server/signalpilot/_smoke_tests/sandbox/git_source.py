# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "sp",
#     "python-gcode==0.1.0",
# ]
#
# [tool.uv.sources]
# python-gcode = { git = "https://github.com/fetlab/python_gcode", rev = "new" }
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def foo():
    import signalpilot
    return


@app.cell
def _():
    import python_gcode
    help(python_gcode)
    return


if __name__ == "__main__":
    app.run()
