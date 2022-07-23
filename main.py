import os

from app import server


def main():
    port = os.getenv("PORT")
    if port is None:
        port = 5000

    server.run(host="0.0.0.0", port=port)


if __name__ == '__main__':
    main()
