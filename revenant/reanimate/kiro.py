"""KiroCli: the thin wrapper around `kiro-cli` used by the headless build (Req 3.2-3.5, 4.5, 4.6)."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable
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


def _key_model(event: Any) -> str | None:
    """The first non-empty `model`/`modelId`/`model_id` value in one event (depth-first)."""
    if isinstance(event, dict):
        for key in MODEL_KEYS:
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        values: Iterable[Any] = event.values()
    elif isinstance(event, list):
        values = event
    else:
        return None
    for value in values:
        found = _key_model(value)
        if found is not None:
            return found
    return None


def _config_model(event: Any) -> str | None:
    """The `currentValue` of the first `configOptions` entry with `id == "model"` (depth-first)."""
    if isinstance(event, dict):
        options = event.get("configOptions")
        if isinstance(options, list):
            for option in options:
                if isinstance(option, dict) and option.get("id") == "model":
                    value = option.get("currentValue")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        values: Iterable[Any] = event.values()
    elif isinstance(event, list):
        values = event
    else:
        return None
    for value in values:
        found = _config_model(value)
        if found is not None:
            return found
    return None


def find_model(events: Iterable[Any]) -> str | None:
    """Req 4.4: the first model key any event reports, else the first `configOptions` model value.

    kiro-cli 3.5.0 reported no model key, only `config_option_update` events whose `configOptions`
    held `{"id": "model", "currentValue": "auto"}`. Returns None when neither exists; never guessed.
    """
    fallback: str | None = None
    for event in events:
        found = _key_model(event)
        if found is not None:
            return found
        if fallback is None:
            fallback = _config_model(event)
    return fallback


def _parse_event(line: str) -> Any:
    try:
        return json.loads(line)
    except ValueError:
        return None


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
        key_models: list[str] = []  # first model key any event reports
        config_models: list[str] = []  # first configOptions model value (fallback)
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
                    if label == "stdout" and not key_models:
                        event = _parse_event(line)
                        key = _key_model(event)
                        if key is not None:
                            key_models.append(key)
                        elif not config_models:
                            config = _config_model(event)
                            if config is not None:
                                config_models.append(config)
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
        model = (key_models or config_models or [None])[0]
        return ChatResult(exit_code=exit_code, timed_out=timed_out, model=model)
