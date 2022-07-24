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

    while ws.connected:

        message = ws.receive(timeout=0)
        if message is not None:
            data = json.loads(message)
            if "source" in data:
                wav = wave.open(data["source"])
            if "command" in data:
                if data["command"] == "STOP":
                    wav.close()
                    wav = None
                    print("Stopped streaming...")
                    continue

        if wav is not None:
            if wav.tell() >= wav.getnframes():
                wav.close()
                wav = None
                print("finished streaming data!")
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

