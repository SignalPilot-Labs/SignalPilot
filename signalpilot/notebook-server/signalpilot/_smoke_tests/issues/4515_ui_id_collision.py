import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
def _():
    import signalpilot

    slider = sp.ui.slider(1, 100)

    class has_mime:
      @staticmethod
      def _mime_():
          # post_execution_hook reuses the name cell index space
          # as the general cell
          # The temp value overwrites the one on the generally cell
          # And because the temp value is "finalized"
          # The cell reference is deleted
          return slider._clone()._mime_()

    has_mime()
    return (slider,)


@app.cell
def _(slider):
    slider.value
    return


if __name__ == "__main__":
    app.run()
