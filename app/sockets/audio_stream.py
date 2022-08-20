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

    conn = Connection(ws)
    while ws.connected:
        conn.handle()


class Connection:

    def dequeue_chunk(self):
        """
        gets the next chunk from the queue to be sent to the client
        """
        if self.queue.not_empty:
            buffer = io.BytesIO()
            chunk: AudioSegment = self.queue.get()
            chunk.export(out_f=buffer, format="mp3")
            yield buffer
        else:
            raise StopIteration

    def enqueue_chunk(self, chunk: AudioSegment):
        """
        enqueues the chunk when finished processing
        """
        self.queue.put(chunk)

    def set_playback_speed(self, val: int):
        """
        changes the playback speed
        """
        if self.channels is not None:
            value = val / 100
            for chan in self.channels:
                chan.filters["speed"].update(value)

    def set_filter_intensity(self, val: int):
        """
        changes the 'lowpass' filter intensity
        """
        if self.channels is not None:
            value = 0.5 - (math.log(val, 10) / 4)
            for chan in self.channels:
                chan.filters["lowpass"].kernel = filter.windowed_sinc_ir(value)

    def get(self):
        """
        sends the duration of the song to the client
        """
        self.ws.send(json.dumps({
            "command": "GET",
            "duration": self.duration
        }))

    def next(self):
        if self.source == "file":
            if self.wav is None:
                return

            if self.wav.tell() >= self.wav.getnframes():
                print("finished transmitting chunks!")
                self.stop()
                return

            # read the next chunk and possess the channels
            raw_wav = self.wav.readframes(BUFFER_SIZE)
            self.channels = filter.process(self.channels, raw_wav, self.wav.getsampwidth())
            processed_audio = filter.combine_wav_channels(self.channels, self.wav.getsampwidth())

            # recreate the wav headers as the `wave` module strips them off :(
            headers = b'RIFF' + struct.pack(
                '<L4s4sLHHLLHH4s', 36 + self.wav.getnframes() * self.wav.getnchannels() * self.wav.getsampwidth(),
                b'WAVE', b'fmt ', 16, 0x0001, self.wav.getnchannels(), self.wav.getframerate(),
                self.wav.getnchannels() * self.wav.getframerate() * self.wav.getsampwidth(),
                self.wav.getnchannels() * self.wav.getsampwidth(), self.wav.getsampwidth() * 8, b'data'
            ) + struct.pack('<L', self.wav.getnframes() * self.wav.getnchannels() * self.wav.getsampwidth())

            # finally, send the processed chunk to the client
            self.ws.send(headers + processed_audio)
        if self.source == "youtube":
            if self.audio is None:
                return

            try:
                self.ws.send(next(self.dequeue_chunk()).read())
            except StopIteration:
                _audio = None
                print("finished transmitting chunks!")
                return

    def stop(self):
        if self.source == "file":
            self.wav.close()
            self.wav = None
            self.channels = None
        if self.source == "youtube":
            pass

        self.query = ""
        self.source = ""
        self.audio = None
        self.queue = Queue()
        print("stopped transmitting...")

    def process_stream(self):
        """

        """

        # initially search YouTube
        res = requests.get(f"{app.URL}/search?" + urllib.parse.urlencode({
            "key": app.KEY,
            "part": "id",
            "maxResults": "1",
            "type": "video",
            "q": self.query
        }), headers={"Accept": "application/json"})
        videoid = res.json()["items"][0]["id"]["videoId"]

        # get audio data from search result
        file = io.BytesIO()
        video = YouTube(f"https://www.youtube.com/watch?v={videoid}")
        stream = video.streams.filter(only_audio=True, file_extension="mp4").first()
        stream.stream_to_buffer(file)
        file.seek(0)

        # break data into a list of io.BytesIO objects
        self.audio = AudioSegment.from_file(file)
        [self.enqueue_chunk(chunk) for chunk in make_chunks(self.audio, chunk_length=1000)]

        # calculate audio duration
        self.duration = {
            "hours": self.audio.duration_seconds // 3600,
            "minuets": self.audio.duration_seconds // 60,
            "seconds": math.floor(self.audio.duration_seconds % 60)
        }

    def handle(self):
        """

        """

        # don't block when timeout is set to 0
        message = self.ws.receive(timeout=0)
        if message is None:
            return

        # load parameters from websocket message
        data = json.loads(message)
        if "q" in data:
            self.query = data["q"]

        if "source" in data:
            self.source = data["source"]

        # stream local file from system
        if self.source == "file":
            if self.wav is None:
                self.wav = wave.open(self.query)
                self.channels = filter.create_channels(self.wav)

                # calculate the duration of the track, so it can be retrieved with the `GET` command.
                length = int(self.wav.getnframes() / self.wav.getframerate())
                hours = length // 3600
                length %= 3600
                minutes = length // 60
                length %= 60
                seconds = length
                self.duration = {
                    "hours": hours,
                    "minuets": minutes,
                    "seconds": seconds
                }

        # stream from YouTube source
        if self.source == "youtube":
            if self.audio is None:
                start = time.perf_counter()
                self.process_stream()
                end = time.perf_counter()
                print(f"Finished processing data in {round(end - start, 2)}")  # benchmarking...

        # handle commands
        if "commands" in data:
            for cmd in data["commands"]:
                if cmd == "GET":
                    self.get()
                if cmd == "UPDATE_FILTER":
                    value = int(data["value"])
                    self.set_filter_intensity(value)
                if cmd == "UPDATE_SPEED":
                    value = int(data["value"])
                    self.set_playback_speed(value)
                if cmd == "NEXT":
                    self.next()
                if cmd == "STOP":
                    self.stop()

    def __init__(self, ws: Websocket):

        # websocket connection
        self.ws = ws

        # queue for storing audio data chunks
        self.queue = Queue()

        # default values
        self.query = ""
        self.source = ""

        #
        self.wav = None
        self.audio = None
        self.channels = None
        self.duration = {"hours": 0, "minuets": 0, "seconds": 0}
