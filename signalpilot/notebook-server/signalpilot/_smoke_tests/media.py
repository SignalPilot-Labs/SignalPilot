# Copyright 2026 SignalPilot. All rights reserved.

import signalpilot

__generated_with = "0.23.5"
app = sp.App()


@app.cell
def _():
    import signalpilot
    import requests
    from io import BytesIO
    import base64

    return BytesIO, base64, sp, requests


@app.cell
def _(sp):
    mic = sp.ui.microphone(label="What is your name?")
    mic
    return (mic,)


@app.cell
def _(mic, sp):
    sp.hstack(
        [sp.audio(mic.value), sp.download(data=mic.value, mimetype="audio/x-wav")]
    )
    return


@app.cell
def _(sp):
    # Note, chrome does not support cross-origin download, so this wont auto download until we proxy the download through the backend
    _src = "https://samplelib.com/lib/preview/mp3/sample-3s.mp3"
    sp.hstack(
        [
            sp.audio(src=_src),
            sp.download(data=_src, label=""),
        ]
    )
    return


@app.cell
def _(BytesIO, base64, sp, requests):
    _src = (
        "https://images.pexels.com/photos/86596/owl-bird-eyes-eagle-owl-86596.jpeg"
    )
    _response = requests.get(_src)
    image_data = BytesIO(_response.content)
    base64str = (
        f"data:image/jpeg;base64,{base64.b64encode(_response.content).decode()}"
    )

    sp.vstack(
        [
            sp.image(src=_src, rounded=True, height=100),
            # Note, chrome does not support cross-origin download, so this wont auto download until we proxy the download through the backend
            sp.download(data=_src, label="Download via URL"),
            sp.image(src=image_data, rounded=True, height=100),
            sp.download(
                data=image_data,
                label="Download via BytesIO",
                mimetype="image/jpeg",
            ),
            sp.image(src=base64str, rounded=True, height=100),
            sp.download(
                data=base64str,
                label="Download via bytes",
                mimetype="image/jpeg",
            ),
        ]
    )
    return


@app.cell
def _(sp):
    import os

    with open(os.path.realpath("docs/_static/array.png"), "rb") as f:
        _image = sp.image(src=f)
        _download = sp.download(
            data=f,
            label="Download local file",
        )

    sp.hstack([_image, _download])
    return


@app.cell
def _(sp):
    # Regression test for #9460: sp.audio with a numpy array goes through the
    # virtual file endpoint, which must serve HTTP Range requests so Safari's
    # <audio> element will play it. Open this notebook in Safari and confirm
    # the player is enabled and audible.
    import math

    import numpy as np

    _sr = 44100
    _samples = 0.01 * np.sin(math.tau * np.cumsum(np.linspace(660, 110, 100000)) / _sr)
    sp.audio(_samples, _sr, normalize=False)
    return


@app.cell
def _(sp):
    sp.video(
        src="https://v3.cdnpk.net/videvo_files/video/free/2013-08/large_watermarked/hd0992_preview.mp4",
        rounded=True,
    )
    return


@app.cell
def _(sp):
    sp.video(
        src="https://v3.cdnpk.net/videvo_files/video/free/2013-08/large_watermarked/hd0992_preview.mp4",
        rounded=True,
        autoplay=True,
        muted=True,
        controls=False,
        width=300,
    )
    return


if __name__ == "__main__":
    app.run()
