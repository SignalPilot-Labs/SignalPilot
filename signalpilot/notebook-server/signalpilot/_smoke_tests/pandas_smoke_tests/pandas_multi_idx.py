import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    import signalpilot
    import pandas as pd
    return sp, pd


@app.cell
def _(sp, pd):
    arrays = [
        ["bar", "bar"],
        ["one", "two"],
    ]
    tuples = list(zip(*arrays))
    index = pd.MultiIndex.from_tuples(tuples, names=["first", "second"])
    named_indexes = pd.Series([1, 2], index=index)

    sp.vstack([sp.md("## Named indexes (works)"), named_indexes])
    return


@app.cell
def _(sp, pd):
    unnamed_indexes = pd.concat(
        {
            "a": pd.DataFrame({"foo": [1]}, index=["hello"]),
            "b": pd.DataFrame({"baz": [2.0]}, index=["world"]),
        }
    )

    sp.md(f"""
    ## Unnamed indexes does not work correctly

    {sp.vstack([sp.plain(unnamed_indexes), unnamed_indexes])}

    ### Using reset_index works but changes structure
    {sp.ui.table(unnamed_indexes.reset_index())}
    """)
    return


@app.cell
def _(sp, pd):
    _multi_idx = pd.MultiIndex.from_tuples([("weight", "kg"), ("height", "m")])
    _df = pd.DataFrame(
        [[1.0, 2.0], [3.0, 4.0]], index=["cat", "dog"], columns=_multi_idx
    )
    _multi_col_stack = _df.stack(future_stack=True)
    sp.vstack([sp.plain(_multi_col_stack), _multi_col_stack])

    sp.vstack(
        [
            sp.md("## Row multi-idx with stack (not working correctly)"),
            sp.plain(_multi_col_stack),
            _multi_col_stack,
        ]
    )
    return


@app.cell
def _(pd):
    cols = pd.MultiIndex.from_arrays(
        [["basic_amt"] * 2, ["NSW", "QLD"]], names=[None, "Faculty"]
    )
    idx = pd.Index(["All", "Full"])
    column_multi_idx = pd.DataFrame([(1, 1), (0, 1)], index=idx, columns=cols)
    return (column_multi_idx,)


@app.cell
def _(column_multi_idx, sp):
    sp.vstack(
        [
            sp.md("## Column multi index (we flatten)"),
            sp.plain(column_multi_idx),
            column_multi_idx,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
