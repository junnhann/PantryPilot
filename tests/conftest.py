"""Shared fixtures."""
import socket
import threading
import time

import pytest
import uvicorn

from app.main import app


@pytest.fixture(scope="session")
def base_url():
    """The real app served on a free local port, so Playwright (and WebSocket clients) can reach it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)
