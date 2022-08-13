import io
import json
import struct
import time
import wave
import requests
import urllib.parse

import app
from audio_processing import filter
from app import socket
from pytube import YouTube
from pytube import request
from simple_websocket.ws \
    import Base as Websocket

from urllib.error import HTTPError


CHUNK_SIZE = 10 * 1024

@socket.route("/stream")
def audio_stream(ws: Websocket):
    wav = None
    _nchannels = 2
    _sampwidth = 0
    _framerate = 0
    _nframes = 0
    _comptype = ""
    _compname = ""
    _duration = {}
    #Creating channel objects before the loop
    channel_1 = filter.Channel()
    channel_1.filters.append(filter.Convolution(filter.moving_average_ir(30)))

    while ws.connected:
        message = ws.receive(timeout=0)
        should_continue = False
        if message is not None:
            data = json.loads(message)
            if "source" in data:
                wav = wave.open(data["source"])
                _nchannels, _sampwidth, _framerate, _nframes, _comptype, _compname = wav.getparams()
                length = int(_nframes / _framerate)
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
            if "commands" in data:
                for command in data["commands"]:
                    if command == "GET":
                        ws.send(json.dumps({
                            "command": "GET",
                            "nchannels": _nchannels,
                            "sampwidth": _sampwidth,
                            "framerate": _framerate,
                            "frames": _nframes,
                            "comptype": _comptype,
                            "compname": _compname,
                            "duration": _duration
                        }))

                    if command == "STOP":
                        if wav is not None:
                            wav.close()
                            wav = None
                            print("stopped transmitting...")
                        should_continue = True

                if should_continue:
                    continue

        if wav is not None:
            if wav.tell() >= wav.getnframes():
                wav.close()
                wav = None
                print("finished transmitting chunks!")
                continue

            sample_rate = wav.getframerate()
            channel_1.buffer = wav.readframes(CHUNK_SIZE)
            channel_1 = filter.process(channel_1, wav.getsampwidth())
            data = b'RIFF' + struct.pack(
                '<L4s4sLHHLLHH4s', 36 + wav.getnframes() * wav.getnchannels() * wav.getsampwidth(),
                b'WAVE', b'fmt ', 16, 0x0001, wav.getnchannels(), wav.getframerate(),
                wav.getnchannels() * wav.getframerate() * wav.getsampwidth(),
                wav.getnchannels() * wav.getsampwidth(), wav.getsampwidth() * 8, b'data'
            ) + struct.pack('<L', wav.getnframes() * wav.getnchannels() * wav.getsampwidth()) + channel_1.buffer

            ws.send(data)
            # time.sleep(0.4 * CHUNK_SIZE / sample_rate)


@socket.route("/youtube")
def youtube_stream(ws: Websocket):

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
