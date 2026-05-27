# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.15.5"
app = sp.App()


@app.cell
async def _():
    import asyncio
    print("hello")
    await asyncio.sleep(1)
    print("world")
    await asyncio.sleep(1)
    print("last one")
    return


if __name__ == "__main__":
    app.run()
