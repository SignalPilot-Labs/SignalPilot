import signalpilot as sp

__generated_with = "0.1.0"
app = sp.App(width="full")


@app.cell
def _():
    import signalpilot as sp

    return (sp,)


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM "main"."raw_order_items" LIMIT 100
        """,
        engine="test"
    )
    return


@app.cell
def _(sp):
    _df = sp.sql(
        f"""
        SELECT * FROM "main"."fct_orders" LIMIT 100
        """,
        engine="test"
    )
    return


@app.cell
def _():
    print("Hello world again!")
    return


@app.cell
def _():
    import time

    print("Starting long-running operation...")
    for i in range(10):
        print(f"Step {i+1}/10 - Progress: {((i+1)/10)*100:.0f}%")
        time.sleep(30)  # Sleep for 30 seconds per iteration

    print("Long-running operation completed! 🎉")
    return


if __name__ == "__main__":
    app.run()
