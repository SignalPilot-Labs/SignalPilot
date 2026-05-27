
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot
    import plotly.express as px
    return sp, px


@app.cell
def _(sp):
    sp.md("# Issue 1064")
    return


@app.cell
def _(px):
    plot1 = px.scatter(x=[0, 1, 4, 9, 16], y=[0, 1, 2, 3, 4])
    plot2 = px.scatter(x=[2, 3, 6, 11, 18], y=[2, 3, 4, 5, 6])
    return plot1, plot2


@app.cell
def _(sp):
    tabs = sp.ui.tabs(
        {
            "💾 Tab 1": "",
            "💾 Tab 2": "",
        }
    )
    return (tabs,)


@app.cell
def _(sp, plot1, plot2, tabs):
    def render_tab_content():
        if tabs.value == "💾 Tab 1":
            return plot1
        elif tabs.value == "💾 Tab 2":
            return plot2
        else:
            return ""


    sp.vstack([tabs.center(), render_tab_content()])
    return


if __name__ == "__main__":
    app.run()
