"""Misbehaving Revenant_Server fixture: fails on import, so uvicorn exits before answering (Req 6.6)."""

from __future__ import annotations

raise RuntimeError("fixture server is broken on import")
