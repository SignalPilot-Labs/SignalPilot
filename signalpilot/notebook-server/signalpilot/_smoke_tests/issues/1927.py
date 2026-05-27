
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    breaker = []
    for i in range(5):
        breaker.append(breaker)
    breaker
    return


if __name__ == "__main__":
    app.run()
