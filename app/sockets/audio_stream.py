import json
import struct
import time
import wave

from app import socket
from simple_websocket.ws \
    import Base as Websocket

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
            frame = wav.readframes(CHUNK_SIZE)
            data = b'RIFF' + struct.pack(
                '<L4s4sLHHLLHH4s', 36 + wav.getnframes() * wav.getnchannels() * wav.getsampwidth(),
                b'WAVE', b'fmt ', 16, 0x0001, wav.getnchannels(), wav.getframerate(),
                wav.getnchannels() * wav.getframerate() * wav.getsampwidth(),
                wav.getnchannels() * wav.getsampwidth(), wav.getsampwidth() * 8, b'data'
            ) + struct.pack('<L', wav.getnframes() * wav.getnchannels() * wav.getsampwidth()) + frame

            ws.send(data)
            time.sleep(0.8 * CHUNK_SIZE / sample_rate)

