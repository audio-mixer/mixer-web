import io
import json
import struct
import time
import wave
import requests
import urllib.parse
import math

import app
from app.processor import filter
from app import socket
from queue import Queue
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
    _source = ""
    _duration = {}

    _queue = Queue()

    # generator for YouTube streaming.
    def get_chunk():
        if _queue.not_empty:
            chunk: AudioSegment = _queue.get()
            buffer = io.BytesIO()
            chunk.export(out_f=buffer, format="mp3")
            yield buffer
        else:
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

                    def process_stream():
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
                        audio = AudioSegment.from_file(file)
                        [_queue.put(chunk) for chunk in make_chunks(audio, chunk_length=1000)]

                        # calculate audio duration
                        duration = {
                            "hours": audio.duration_seconds // 3600,
                            "minuets": audio.duration_seconds // 60,
                            "seconds": math.floor(audio.duration_seconds % 60)
                        }

                        return audio, duration

                    start = time.perf_counter()
                    _audio, _duration = process_stream()
                    end = time.perf_counter()
                    print(f"Finished processing data in {round(end - start, 2)}")
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
                        if _audio is not None:
                            _audio = None

                        print("stopped transmitting...")

