import signalpilot

__generated_with = "0.17.8"
app = sp.App(width="medium")


@app.function
async def sleep(seconds):
    import asyncio

    tasks = [asyncio.create_task(asyncio.sleep(s, s)) for s in seconds]
    for future in asyncio.as_completed(tasks):
        yield await future


@app.cell
async def _():
    import signalpilot

    async def test_progress_async() -> None:
        ait = sleep([0.3, 0.2, 0.1])
        result = [s async for s in sp.status.progress_bar(ait, total=3)]
        assert result == [0.1, 0.2, 0.3]

    await test_progress_async()
    return (sp,)


@app.cell
async def _(sp):
    async def test_progress_slow_async() -> None:
        test_durations = [250, 35, 10, 1.5]
        ait = sleep(test_durations)
        result = [
            s async for s in sp.status.progress_bar(ait, total=len(test_durations))
        ]

        assert result == sorted(test_durations)

    await test_progress_slow_async()
    return


if __name__ == "__main__":
    app.run()
