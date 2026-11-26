"""Misbehaving Revenant_Server fixture: never answers (Req 6.1, 6.6).

The import blocks, so uvicorn never binds its port; the 30-second wait (shortened in tests) expires.
"""

from __future__ import annotations

import time

time.sleep(3600)

app = None
