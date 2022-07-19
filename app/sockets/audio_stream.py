from app import socket


@socket.route("/stream")
def audio_stream(ws):

    while ws.connected:
        data = ws.receive()
        print(data)

        # send back what is received. (for testing purposes)
        ws.send(data)
