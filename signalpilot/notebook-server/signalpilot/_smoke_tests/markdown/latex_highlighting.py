import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _(sp):
    sp.md(
        """
    ## Markdown / Latex Highlighting

    ```ts
    console.log("highlight code fences")
    ```

    ```python
    def lang_python():
        pass
    ```

    ```
    def no_language():
        pass
    ```

    **bold**

    _italic_

    $\sigma\sqrt{100}$

    $$
    \sigma\sqrt{100}
    $$

    \[ \sigma\sqrt{100} \]

    \( \sigma\sqrt{100} \)
    """
    )
    return


@app.cell
def _():
    import signalpilot
    return (sp,)


if __name__ == "__main__":
    app.run()
