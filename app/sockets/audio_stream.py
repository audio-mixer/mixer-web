import io
import json
import struct
import wave
import requests
import urllib.parse
import math

import app
from audio_processing import filter
from app import socket
from pytube import YouTube
from pytube import request
from simple_websocket.ws \
    import Base as Websocket

from urllib.error import HTTPError

BUFFER_SIZE = 2048


@socket.route("/stream")
def audio_stream(ws: Websocket):
    """
    `audio_stream` is the websocket endpoint.

    when a client connects to the socket,
    they will send a `source` parameter that
    will fetch a wav file on the server.

    this function will continue until the
    connection is closed by the client.

    the server can accept other parameters such
    as commands that will alter the functionality
    of this socket.

    available commands:
        STOP: stops transmitting chunks (does not close the connection)
        GET: gets the duration of the audio file for cosmetic display on the client
        NEXT: gets the next chunk to be processed and sent back to the client
        UPDATE_SPEED: changes the kernel of the speed filter to increase/decrease playback speed
        UPDATE_FILTER: changes the kernel of the lowpass filter to increase/decrease filter intensity

    example send:
        ```js
        ws.send(JSON.stringify({
            source: "example.wav"
        }))
        ```

    example command send:
    the `commands` property accepts an array.
    you can send multiple commands at a time,
    the server will handle them in the order
    they were sent.
        ```js
        ws.send(JSON.stringify({
            commands: ["GET"]
        }))
        ```
    """

    wav = None
    channels = None
    _duration = {}

    # keep connection open.
    while ws.connected:

        # don't block when timeout is set to 0
        message = ws.receive(timeout=0)
        should_continue = False
        if message is not None:

            data = json.loads(message)

            # read the `source` property sent from the client
            # and open `wave` object for reading.
            if "source" in data:
                wav = wave.open(data["source"])

                # calculate the duration of the track, so it can be retrieved with the `GET` command.
                length = int(wav.getnframes() / wav.getframerate())
                hours = length // 3600
                length %= 3600
                minutes = length // 60
                length %= 60
                seconds = length
                _duration = {
                    "hours": hours,
                    "minuets": minutes,
                    "seconds": seconds
                }

                # create `filter.Channel()'s` object for possessing filters.
                channels = filter.create_channels(wav)

            # read the `commands` property sent from the client
            if "commands" in data:
                for command in data["commands"]:

                    # handles the `GET` command
                    if command == "GET":
                        ws.send(json.dumps({
                            "command": "GET",
                            "duration": _duration
                        }))

                    # handles the `NEXT` command
                    if command == "NEXT":
                        if wav is not None:
                            if wav.tell() >= wav.getnframes():
                                wav.close()
                                wav = None
                                print("finished transmitting chunks!")
                                continue

                            # read the next chunk and possess the channels
                            raw_wav = wav.readframes(BUFFER_SIZE)
                            channels = filter.process(channels, raw_wav, wav.getsampwidth())
                            processed_audio = filter.combine_wav_channels(channels, wav.getsampwidth())

                            # recreate the wav headers as the `wave` module strips them off :(
                            headers = b'RIFF' + struct.pack(
                                '<L4s4sLHHLLHH4s', 36 + wav.getnframes() * wav.getnchannels() * wav.getsampwidth(),
                                b'WAVE', b'fmt ', 16, 0x0001, wav.getnchannels(), wav.getframerate(),
                                wav.getnchannels() * wav.getframerate() * wav.getsampwidth(),
                                wav.getnchannels() * wav.getsampwidth(), wav.getsampwidth() * 8, b'data'
                            ) + struct.pack('<L', wav.getnframes() * wav.getnchannels() * wav.getsampwidth())

                            # finally, send the processed chunk to the client
                            ws.send(headers + processed_audio)

                    # handles the `UPDATE_FILTER` command
                    if command == "UPDATE_FILTER":
                        if channels is not None:
                            value = int(data["value"])
                            value = 0.5 - (math.log(value,10) / 4)
                            for chan in channels:
                                chan.filters["lowpass"].kernel = filter.windowed_sinc_ir(value)

                    # handles the `UPDATE_SPEED` command
                    if command == "UPDATE_SPEED":
                        if channels is not None:
                            value = int(data["value"])
                            value = value/100
                            for chan in channels:
                                chan.filters["speed"].update(value)

                    # handles the `STOP` command
                    if command == "STOP":
                        if wav is not None:
                            wav.close()
                            wav = None
                            print("stopped transmitting...")
                        should_continue = True

                if should_continue:
                    continue


@socket.route("/youtube")
def youtube_stream(ws: Websocket):
    """
    This function is currently unused.
    It was intended to get an audio stream
    from YouTube so that it could be processed
    as well, but the data returned was in mp3
    format... :(

    This function was left in so that we could
    return to this problem.
    """

    _buffer = io.BytesIO()
    _stream = None
    _audio = None
    _bytes_read = 0
    _duration = {}

    while ws.connected:
        message = ws.receive(timeout=0)
        should_continue = False
        if message is not None:
            data = json.loads(message)
            if "q" in data:
                _query = data["q"]

                # initially search YouTube
                res = requests.get(f"{app.URL}/search?" + urllib.parse.urlencode({
                    "key": app.KEY,
                    "part": "id",
                    "maxResults": "1",
                    "type": "video",
                    "q": _query
                }), headers={"Accept": "application/json"})
                videoid = res.json()["items"][0]["id"]["videoId"]

                # get metadata about the video
                res = requests.get(f"{app.URL}/videos?" + urllib.parse.urlencode({
                    "id": videoid,
                    "key": app.KEY,
                    "part": "contentDetails",
                }), headers={"Accept": "application/json"})
                iso8601 = res.json()["items"][0]["contentDetails"]["duration"]
                _duration = _parse_iso_datetime(iso8601)

                # get audio data from search result
                video = YouTube(f"https://www.youtube.com/watch?v={videoid}")
                _audio = video.streams.filter(only_audio=True, file_extension="mp4").first()

                try:
                    _stream = request.stream(url=_audio.url)
                except HTTPError:
                    _stream = request.seq_stream(url=_audio.url)

            if "commands" in data:
                for command in data["commands"]:
                    if command == "GET":
                        ws.send(json.dumps({
                            "command": "GET",
                            "duration": _duration
                        }))
                    if command == "STOP":
                        _audio = None
                        _stream = None
                        _buffer = io.BytesIO()
                        _buffer2 = io.BytesIO()
                        should_continue = True
                        print("stopped transmitting...")

                if should_continue:
                    continue

        if _audio is not None:
            if _bytes_read >= _audio.filesize:
                _audio = None
                _stream = None
                _bytes_read = 0
                _buffer = io.BytesIO()
                print("finished transmitting chunks!")
                continue

            for chunk in _stream:
                _bytes_read += len(chunk)
                _buffer.write(chunk)

            _buffer.seek(0)
            ws.send(_buffer.read())


def _parse_iso_datetime(isostring: str) -> dict:
    """
    this was used in the `youtube_stream` function...
    """
    (v, h, m, s) = ("", 0, 0, 0)
    for char in isostring:
        try:
            v += v.join(f"{str(int(char))}")
        except ValueError:
            if char == "H":
                h = int(v)
                v = ""
            if char == "M":
                m = int(v)
                v = ""
            if char == "S":
                s = int(v)
                v = ""

    return {
        "hours": h,
        "minuets": m,
        "seconds": s
    }
