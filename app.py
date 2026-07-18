import os

from marketplace import create_app
from marketplace.extensions import socketio


app = create_app()


if __name__ == "__main__":
    socketio.run(
        app,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
