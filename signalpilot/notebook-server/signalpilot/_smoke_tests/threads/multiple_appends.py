import signalpilot

__generated_with = "0.20.1"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import time
    import threading

    return sp, threading, time


@app.cell
def _(sp, threading, time):
    def append():
        for i in range(3):
            sp.output.append(f"{i}: Hello from {threading.get_ident()}")
            time.sleep(1)

    return (append,)


@app.cell
def _(sp, threading, time):
    def replace():
        for i in range(3):
            sp.output.replace(f"{i}: Hello from {threading.get_ident()}")
            time.sleep(1)

    return (replace,)


@app.cell
def _(sp):
    def run_threads(fn):
        _threads = [sp.Thread(target=fn) for _ in range(3)]
        for _t in _threads:
            _t.start()
        for _t in _threads:
            _t.join()

    return (run_threads,)


@app.cell
def _(append, run_threads):
    run_threads(append)
    return


@app.cell
def _(replace, run_threads):
    run_threads(replace)
    return


if __name__ == "__main__":
    app.run()
