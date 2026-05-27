# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sp",
#     "traitlets",
#     "anywidget",
#     "pandas",
#     "altair",
#     "drawdata",
# ]
# ///

import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    return (sp,)


@app.cell
def _():
    import anywidget
    import traitlets


    class CounterWidget(anywidget.AnyWidget):
        # Widget front-end JavaScript code
        _esm = """
        function render({ model, el }) {
          let getCount = () => model.get("count");
          let button = document.createElement("button");
          button.innerHTML = `count is ${getCount()}`;
          button.addEventListener("click", () => {
            model.set("count", getCount() + 1);
            model.save_changes();
          });
          model.on("change:count", () => {
            button.innerHTML = `count is ${getCount()}`;
          });
          el.appendChild(button);
        }
    	export default { render };
        """
        _css = """
        button {
          padding: 5px !important;
          border-radius: 5px !important;
          background-color: #f0f0f0 !important;

          &:hover {
            background-color: lightblue !important;
            color: white !important;
          }
        }
        """

        # Stateful property that can be accessed by JavaScript & Python
        count = traitlets.Int(0).tag(sync=True)
    return (CounterWidget,)


@app.cell
def _(CounterWidget):
    # Non-reactive
    w = CounterWidget()
    w
    return (w,)


@app.cell
def _(w):
    # Non-reactive, but class is cached
    w
    return


@app.cell
def _(w):
    w.trait_values()["count"]
    return


@app.cell
def _(CounterWidget, sp):
    w_reactive = sp.ui.anywidget(CounterWidget())
    w_reactive
    return (w_reactive,)


@app.cell
def _(w_reactive):
    w_reactive
    return


@app.cell
def _(w_reactive):
    w_reactive.value
    return


@app.cell
def _(w_reactive):
    w_reactive.widget.trait_values()["count"]
    return


@app.cell
def _():
    import altair as alt
    import pandas as pd
    return alt, pd


@app.cell
def _(sp):
    from drawdata import ScatterWidget

    dd_widget = sp.ui.anywidget(ScatterWidget())
    dd_widget
    return (dd_widget,)


@app.cell(hide_code=True)
def _(alt, dd_widget, sp, pd):
    sp.stop(not dd_widget.value["data"])
    df = pd.DataFrame(dd_widget.value["data"])
    chart = alt.Chart(df).mark_point().encode(x="x", y="y", color="color")
    sp.ui.altair_chart(chart)
    return


if __name__ == "__main__":
    app.run()
