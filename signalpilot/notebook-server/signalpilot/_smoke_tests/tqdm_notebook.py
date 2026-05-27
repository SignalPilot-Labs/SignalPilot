
import signalpilot

__generated_with = "0.15.5"
app = sp.App(width="medium")


@app.cell
def _():
    from tqdm.notebook import tqdm

    import time
    return time, tqdm


@app.cell
def _(time, tqdm):
    for i in tqdm(range(10)):
        time.sleep(0.1)
    return


if __name__ == "__main__":
    app.run()
