"""KiroCli: the thin wrapper around `kiro-cli` used by the headless build (Req 3.2-3.5, 4.5, 4.6)."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from revenant.reanimate.errors import ReanimateError

CHAT_PROMPT = "Read reanimate-prompt.md in this directory and follow it exactly."
CHAT_ARGS = (
    "chat",
    "--v3",
    "--no-interactive",
    "--trust-workspace",
    "--trust-tools=fs_read,fs_write",
    "--output-format",
    "stream-json",
    CHAT_PROMPT,
)
CHAT_TIMEOUT = 900.0
VERSION_TIMEOUT = 30.0
WHOAMI_TIMEOUT = 60.0
STOP_GRACE = 10.0
MODEL_KEYS = ("model", "modelId", "model_id")


@dataclass(frozen=True)
class ChatResult:
    """How one `kiro-cli chat` run ended. `exit_code` is None when it was stopped by the timeout."""

    exit_code: int | None
    timed_out: bool
    model: str | None


def _identity(text: str) -> str:
    return text


def find_model(event: Any) -> str | None:
    """The first non-empty model id found in a parsed stream-json event (depth-first), else None."""
    if isinstance(event, dict):
        for key in MODEL_KEYS:
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in event.values():
            found = find_model(value)
            if found is not None:
                return found
    elif isinstance(event, list):
        for value in event:
            found = find_model(value)
            if found is not None:
                return found
    return None


def _model_from_line(line: str) -> str | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return find_model(event)


class KiroCli:
    """Runs `command + [...]`; tests pass `[sys.executable, "<abs>/tests/reanimate/fake_kiro.py"]`."""

    def __init__(self, command: list[str] | None = None) -> None:
        self.command = list(command) if command else ["kiro-cli"]

    def available(self) -> bool:
        """True when the executable is on the PATH or is an existing file path."""
        exe = self.command[0]
        return shutil.which(exe) is not None or Path(exe).is_file()

    def whoami(self) -> int:
        """Exit code of `kiro-cli whoami`; its output is discarded and never stored (Req 7.2)."""
        try:
            completed = subprocess.run(
                [*self.command, "whoami"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=WHOAMI_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return -1
        return completed.returncode

    def version(self, timeout: float = VERSION_TIMEOUT) -> str:
        """Stripped stdout of `kiro-cli --version`; non-zero, empty or slow raises (Req 4.5, 4.6)."""
        try:
            completed = subprocess.run(
                [*self.command, "--version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ReanimateError(
                "kiro", f"kiro-cli --version ran longer than {timeout:g} seconds", 2
            ) from None
        except OSError as exc:
            raise ReanimateError("kiro", f"kiro-cli --version could not start: {exc}", 2) from None
        if completed.returncode != 0:
            raise ReanimateError(
                "kiro", f"kiro-cli --version exited with code {completed.returncode}", 2
            )
        text = (completed.stdout or "").strip()
        if not text:
            raise ReanimateError("kiro", "kiro-cli --version printed nothing", 2)
        return text

    def chat(
        self,
        cwd: Path,
        log: Path,
        timeout: float = CHAT_TIMEOUT,
        redactor: Callable[[str], str] = _identity,
    ) -> ChatResult:
        """Run the headless chat in `cwd`, streaming labelled lines to `log` (replaced)."""
        log.parent.mkdir(parents=True, exist_ok=True)
        lock = threading.Lock()
        models: list[str] = []
        with log.open("w", encoding="utf-8", newline="\n") as sink:
            proc = subprocess.Popen(
                [*self.command, *CHAT_ARGS],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            def pump(stream: IO[str], label: str) -> None:
                for raw in stream:
                    line = raw.rstrip("\r\n")
                    if label == "stdout" and not models:
                        model = _model_from_line(line)
                        if model is not None:
                            models.append(model)
                    with lock:
                        sink.write(f"{label}: {redactor(line)}\n")
                        sink.flush()
                stream.close()

            assert proc.stdout is not None and proc.stderr is not None
            readers = [
                threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True),
                threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True),
            ]
            for reader in readers:
                reader.start()
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.terminate()
                try:
                    proc.wait(timeout=STOP_GRACE)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for reader in readers:
                reader.join(timeout=STOP_GRACE)
        exit_code = None if timed_out else proc.returncode
        return ChatResult(
            exit_code=exit_code, timed_out=timed_out, model=models[0] if models else None
        )
