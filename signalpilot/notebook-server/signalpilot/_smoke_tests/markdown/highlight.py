import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _(sp):
    sp.md(
        """
    ```
    >>> # pycon (omitted)
    >>> def foo():
    >>>    pass
    ```

    ```
    # python (omitted)
    def foo():
        return range(1, 100)
    return x + y
    ```

    ```pycon
    >>> def foo():
    >>>    pass
    ```

    ```python
    # python
    def foo():
        pass
    x + y
    ```
    """
    )
    return


@app.cell
def _(sp):
    sp.md(
        r"""
    ```js
    // js
    const myVar = "";
    ```

    ```
    import { foo } from "bar";
    // js omitted
    var myVar = "";
    ```
    """
    )
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
