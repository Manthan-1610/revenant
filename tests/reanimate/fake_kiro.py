"""Stub kiro-cli for offline tests: handles `whoami`, `--version` and `chat`.

Run as `[sys.executable, "<abs>/tests/reanimate/fake_kiro.py", ...]`. Environment:
- `FAKE_KIRO_MODE`: `ok` (default, copies `fixtures/server.py` into the cwd), `fail` (chat exits 1),
  `sleep` (chat prints a line, then sleeps `FAKE_KIRO_SLEEP` seconds, default 60), `noserver`
  (chat exits 0 without writing `server.py`), `whoami-fail`, `version-fail`, `version-empty`,
  `version-slow`, `touch-repo` / `delete-repo` (chat writes the server, then writes or deletes the
  file named by `FAKE_KIRO_TARGET`, standing in for a trusted `fs_write` outside the workspace),
  `leak` (like `ok`, but `whoami`, `--version` and `chat` also print `KIRO_API_KEY`, a fake email
  and `FAKE_KIRO_HOME` in native, forward-slash, JSON-escaped and percent-encoded spellings).
- `FAKE_KIRO_ARGV`: when set, the argv (after the script path) is written there as JSON.
- `FAKE_KIRO_MODEL`: model id reported by a stream-json event (default `fake-model-1`); empty means
  no event reports a model, and so does `none` (Windows removes empty environment values).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

FIXTURE_SERVER = Path(__file__).resolve().parent / "fixtures" / "server.py"


def _out(data: bytes, stream=None) -> None:
    target = stream or sys.stdout.buffer
    target.write(data)
    target.flush()


def _event(payload: dict) -> None:
    _out(json.dumps(payload).encode("utf-8") + b"\n")


def _leak_lines() -> list[str]:
    """Secrets for `leak` mode: `KIRO_API_KEY`, a fake email and `FAKE_KIRO_HOME` in every spelling."""
    key = os.environ.get("KIRO_API_KEY", "")
    home = os.environ.get("FAKE_KIRO_HOME", "")
    slash = home.replace("\\", "/")
    lines = [
        f"key={key} email=ghost@example.invalid",
        f"native {home}\\server.py",
        f"slash {slash}/server.py",
        json.dumps({"path": home + "\\server.py"}),  # JSON-escaped spelling
    ]
    if len(home) > 1 and home[1] == ":":
        rest = slash[2:]
        lines.append(f"uri file:///{home[0].lower()}%3A{rest}/server.py")
        lines.append(f"uri2 {home[0].upper()}%3A{home[2:].replace(chr(92), '%5C')}%5Cserver.py")
    return lines


def main(argv: list[str]) -> int:
    mode = os.environ.get("FAKE_KIRO_MODE", "ok")
    argv_file = os.environ.get("FAKE_KIRO_ARGV")
    if argv_file:
        Path(argv_file).write_text(json.dumps(argv), encoding="utf-8")
    if not argv:
        return 2
    command = argv[0]
    leak = _leak_lines() if mode == "leak" else []
    if command == "whoami":
        _out(b"Logged in as ghost (stub)\n")
        for line in leak:
            _out(line.encode() + b"\n")
            _out(line.encode() + b"\n", sys.stderr.buffer)
        return 1 if mode == "whoami-fail" else 0
    if command == "--version":
        if mode == "version-fail":
            return 3
        if mode == "version-slow":
            time.sleep(float(os.environ.get("FAKE_KIRO_SLEEP", "60")))
        if mode != "version-empty":
            suffix = " " + " | ".join(leak) if leak else ""
            _out(f"kiro-cli 3.5.0 → fake ✓{suffix}\n".encode())
        return 0
    if command != "chat":
        return 2

    model = os.environ.get("FAKE_KIRO_MODEL", "fake-model-1")
    if model == "none":  # Windows drops empty env values, so tests use this sentinel
        model = ""
    _event({"type": "session_start", "session": "stub"})
    if model:
        _event({"type": "session_info", "params": {"modelId": model}})
    _out("thinking → done ✓ ".encode() + b"\xff\n")
    _out("stderr note → ✓\n".encode(), sys.stderr.buffer)
    for line in leak:
        _out(line.encode() + b"\n")
        _out(line.encode() + b"\n", sys.stderr.buffer)
        if not line.startswith("{"):  # re-escaping JSON text is not a Home_Path spelling
            _event({"type": "agent_message", "text": line})
    if mode == "fail":
        _out(b"stub failure\n", sys.stderr.buffer)
        return 1
    if mode == "sleep":
        time.sleep(float(os.environ.get("FAKE_KIRO_SLEEP", "60")))
        return 0
    if mode in ("ok", "leak", "touch-repo", "delete-repo"):
        shutil.copyfile(FIXTURE_SERVER, Path.cwd() / "server.py")
    if mode == "touch-repo":
        Path(os.environ["FAKE_KIRO_TARGET"]).write_bytes(b"written by a trusted fs_write\n")
    if mode == "delete-repo":
        Path(os.environ["FAKE_KIRO_TARGET"]).unlink()
    _event({"type": "end_turn"})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
