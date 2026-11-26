"""Misbehaving Revenant_Server fixture: refuses to stop when asked (Req 6.5).

On POSIX, `Popen.terminate()` sends SIGTERM; this app ignores SIGTERM once uvicorn has started
(overriding uvicorn's own handler) and its lifespan shutdown hangs, so only `kill()` ends it.
On Windows, `terminate()` is already `TerminateProcess`, a hard kill that cannot be ignored.
Every request answers 503, so the demo Check fails and the stop follows at once.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    yield
    await asyncio.sleep(3600)  # shutdown never finishes


app = FastAPI(lifespan=lifespan)


@app.get("/{path:path}")
def anything(path: str) -> Response:
    return Response(b"stubborn", status_code=503, media_type="text/plain")
