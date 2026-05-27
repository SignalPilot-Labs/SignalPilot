import signalpilot

__generated_with = "0.20.1"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import random
    import time
    import threading

    return sp, random, threading, time


@app.cell
def _(sp, random, threading, time):
    def step(pbar: sp.status.progress_bar, work: int):
        for _ in range(work):
            # Sleep... or anything else that releases GIL
            time.sleep(random.uniform(0.5, 1))
            pbar.update(
                subtitle=f"work completed by thread {threading.get_ident()}"
            )

    return (step,)


@app.cell
def _(sp, random, step, time):
    total = 30
    with sp.status.progress_bar(total=total) as pbar:
        n_threads = 4
        work = total // n_threads
        remainder = total % n_threads
        threads = [
            sp.Thread(target=step, args=(pbar, work))
            for _ in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for _ in range(remainder):
            time.sleep(random.uniform(0.5, 1))
            pbar.update(subtitle="work completed by main thread")
    return


if __name__ == "__main__":
    app.run()
