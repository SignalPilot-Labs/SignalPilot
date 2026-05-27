
import signalpilot

__generated_with = "0.19.7"
app = sp.App(app_title="sp for Jupyter users")


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    # sp for Jupyter users

    This notebook explains important differences between Jupyter and sp. If you're
    familiar with Jupyter and are trying out sp for the first time, read on!
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Reactive execution

    The biggest difference between sp and Jupyter is *reactive execution*.

    Try updating the value of x in the next cell, then run it.
    """)
    return


@app.cell
def _():
    x = 0; x
    return (x,)


@app.cell
def _(x):
    y = x + 1; y
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    sp 'reacts' to the change in `x` and automatically recalculates `y`!

    **Explanation.** sp reads the code in your cells and understands the
    dependences between them, based on the variables that each cell declares and
    references. When you execute one cell, sp automatically executes all other
    cells that depend on it, not unlike a spreadsheet.

    In contrast, Jupyter requires you to manually run each cell.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ### Why?

    Reactive execution frees you from the tedious task of manually re-running cells.

    It also ensures that your code and outputs remain in sync:

    - You don't have to worry about whether you forgot to re-run a cell.
    - When you delete a cell, its variables are automatically removed from
    program memory. Affected cells are automatically invalidated.

    This makes sp notebooks as reproducible as regular Python scripts.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md("""
    ## Interactive elements built-in

    sp comes with a [large library of UI elements](https://docs.signalpilot.ai/docs/) that are automatically
    synchronized with Python.
    """)
    return


@app.cell
def _():
    import signalpilot

    return (sp,)


@app.cell
def _(sp):
    slider = sp.ui.slider(start=1, stop=10, label="$x$")
    slider
    return (slider,)


@app.cell
def _(slider):
    slider.value
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(rf"""
    **Explanation.** sp is both a notebook and a library. Import `sp as
    mo` and use `sp.ui` to get access to powerful UI elements.

    UI elements assigned to variables are automatically plugged into sp's
    reactive execution model: interactions automatically trigger execution of
    cells that refer to them.

    In contrast, Jupyter's lack of reactivity makes IPyWidgets difficult to use.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Shareable as apps

    sp notebooks can be shared as read-only web apps: just serve it with

    ```sp run your_notebook.py```

    at the command-line.

    Not every sp notebook needs to be shared as an app, but sp makes it
    seamless to do so if you want to. In this way, sp works as a replacement
    for both Jupyter and Streamlit.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Cell order

    In sp, cells can be arranged in any order — sp figures out the one true way to execute them based on variable declarations and references (in a ["topologically sorted"](https://en.wikipedia.org/wiki/Topological_sorting#:~:text=In%20computer%20science%2C%20a%20topological,before%20v%20in%20the%20ordering.) order)
    """)
    return


@app.cell
def _(z):
    z.value
    return


@app.cell
def _(sp):
    z = sp.ui.slider(1, 10, label="$z$"); z
    return (z,)


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    This lets you arrange your cells in the way that makes the most sense to you. For example, put helper functions and imports at the bottom of a notebook, like an appendix.

    In contrast, Jupyter notebooks implicitly assume a top-to-bottom execution order.
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Re-assigning variables

    sp disallows variable re-assignment. Here is something commonly done in Jupyter notebooks that cannot be done in sp:
    """)
    return


@app.cell
def _():
    df = 0
    return (df,)


@app.cell
def _():
    df = 1
    return (df,)


@app.cell
def _(df):
    results = df.groupby(["my_column"]).sum()
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    **Explanation.** `results` depends on `df`, but which value of `df` should it use? Reactivity makes it impossible to answer this question in a sensible way, so sp disallows variable reassignment.

    If you run into this error, here are your options:

    1. combine definitions into one cell
    2. prefix variables with an underscore (`_df`) to make them local to the cell
    3. wrap your code in functions, or give your variables more descriptive names
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(rf"""
    ## Markdown

    sp notebooks are stored as pure Python, but you can still write Markdown:
    `import sp` and use `sp.md`.

    /// details | What about markdown & SQL "cells"?

    You may notice sp UI has markdown and SQL cells in the editor. These are
    conveniences that use `sp.md` and `sp.sql` under the hood, with nicer
    ergonomics for authoring.
    ///
    """)
    return


@app.cell
def _(sp, slider):
    sp.md(
        f"""
        The value of {slider} is {slider.value}.
        """
    )
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    **Explanation.** By lifting Markdown into Python, sp lets you construct
    dynamic Markdown parameterized by arbitrary Python elements. sp knows
    how to render its own elements, and you can use `sp.as_html` to render other
    objects, like plots.

    _Tip: toggle a markdown view via `Cmd/Ctrl-Shift-M` in an empty cell._
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Notebook files

    Jupyter saves notebooks as JSON files, with outputs serialized in them. This is helpful as a record of your plots and other results, but makes notebooks difficult to version and reuse.

    ### sp notebooks are Python scripts
    sp notebooks are stored as pure Python scripts. This lets you version them with git, execute them with the command line, and re-use logic from one notebook in another.

    ### sp notebooks do not store outputs
    sp does _not_ save your outputs in the file; if you want them saved, make sure to save them to disk with Python, or export to HTML via the notebook menu.

    ### sp notebooks are versionable with git

    sp is designed so that small changes in your code yield small git diffs!
    """)
    return


@app.cell(hide_code=True)
def _(sp):
    sp.md(r"""
    ## Parting thoughts

    sp is a **reinvention** of the Python notebook as a reproducible, interactive, and shareable Python program, instead of an error-prone scratchpad.

    We believe that the tools we use shape the way we think — better tools, for better minds. With sp, we hope to provide the Python community with a better programming environment to do research and communicate it; to experiment with code and share it; to learn computational science and teach it.

    The sp editor and library have many features not discussed here.
    Check out [our docs](https://docs.signalpilot.ai/docs/) to learn more!

    _This guide was adapted from [Pluto for Jupyter
    users](https://featured.plutojl.org/basic/pluto%20for%20jupyter%20users).
    We ❤️ Pluto.jl!_
    """)
    return


if __name__ == "__main__":
    app.run()
