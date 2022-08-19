import io
import json
import struct
import wave
import requests
import urllib.parse
import math

import app
from app.processor import filter
from app import socket
from pytube import YouTube
from pydub import AudioSegment
from pydub.utils import *
from simple_websocket.ws \
    import Base as Websocket


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
    _audio = None
    _buffer = []
    _source = ""
    _duration = {}

    # generator for YouTube streaming.
    def get_chunk():
        try:
            ch = _buffer[0]
            _buffer.pop(0)

            yield ch
        except IndexError:
            raise StopIteration

    # keep connection open.
    while ws.connected:

        # don't block when timeout is set to 0
        message = ws.receive(timeout=0)
        if message is not None:

            data = json.loads(message)

            # read the `source` property sent from the client
            # and open `wave` object for reading.
            if "source" in data:
                _source = data["source"]
                if _source == "file":
                    wav = wave.open(data["q"])

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

                if _source == "youtube":
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

                    # get audio data from search result
                    file = io.BytesIO()
                    video = YouTube(f"https://www.youtube.com/watch?v={videoid}")
                    stream = video.streams.filter(only_audio=True, file_extension="mp4").first()
                    stream.stream_to_buffer(file)
                    file.seek(0)

                    # break data into a list of io.BytesIO objects
                    _audio = AudioSegment.from_file(file)
                    chunks = make_chunks(_audio, chunk_length=1000)  # 200ms
                    for i in range(len(chunks)):
                        buffer = io.BytesIO()
                        chunk: AudioSegment = chunks[i]
                        chunk.export(out_f=buffer, format="mp3")

                        _buffer.append(buffer)

                    # calculate audio duration
                    _duration = {
                        "hours": _audio.duration_seconds // 3600,
                        "minuets": _audio.duration_seconds // 60,
                        "seconds": math.floor(_audio.duration_seconds % 60)
                    }
            else:
                pass

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
                        if _source == "file":
                            if wav is not None:
                                if wav.tell() >= wav.getnframes():
                                    wav.close()
                                    wav = None
                                    channels = None
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

                        if _source == "youtube":
                            if _audio is not None:
                                try:
                                    ws.send(next(get_chunk()).read())
                                except StopIteration:
                                    _audio = None
                                    _buffer = []
                                    print("finished transmitting chunks!")
                                    continue

                    # handles the `UPDATE_FILTER` command
                    if command == "UPDATE_FILTER":
                        if channels is not None:
                            value = int(data["value"])
                            value = 0.5 - (math.log(value, 10) / 4)
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
                            channels = None
                            _audio = None
                            _buffer = []
                            print("stopped transmitting...")
