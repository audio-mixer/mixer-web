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

    while ws.connected:

        message = ws.receive()
        data = json.loads(message)

        with wave.open(data["source"], 'rb') as wav:

            complete = False
            sample_rate = wav.getframerate()
            while not complete:
                if wav.tell() >= wav.getnframes():
                    complete = True

                frame = wav.readframes(CHUNK_SIZE)
                data = b'RIFF' + struct.pack(
                    '<L4s4sLHHLLHH4s', 36 + wav.getnframes() * wav.getnchannels() * wav.getsampwidth(),
                    b'WAVE', b'fmt ', 16, 0x0001, wav.getnchannels(), wav.getframerate(),
                    wav.getnchannels() * wav.getframerate() * wav.getsampwidth(),
                    wav.getnchannels() * wav.getsampwidth(), wav.getsampwidth() * 8, b'data'
                ) + struct.pack('<L', wav.getnframes() * wav.getnchannels() * wav.getsampwidth()) + frame

                ws.send(data)
                time.sleep(0.8 * CHUNK_SIZE / sample_rate)

        print("finished streaming data!")
