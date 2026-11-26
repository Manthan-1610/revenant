"""Post-build Check: run the Revenant_Server under uvicorn and test it (Req 6.1-6.6)."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import httpx

from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.record import CheckResult, DonorEntry, DonorIndex

CheckName = Literal["demo", "unknown_symbol", "weekly"]
CHECK_NAMES: tuple[CheckName, ...] = ("demo", "unknown_symbol", "weekly")
HEADER_LINE = b"Date,Open,High,Low,Close,Volume,Adj Close"
DEMO_PATH = "/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv"
WEEKLY_PATH = DEMO_PATH.replace("&g=d&", "&g=w&", 1)
UNKNOWN_SYMBOL = "NODONOR"
DEMO_DATES = ("2016-01-08", "2016-01-07", "2016-01-06", "2016-01-05", "2016-01-04")
READY_TIMEOUT = 30.0
REQUEST_TIMEOUT = 10.0
STOP_TIMEOUT = 10.0
POLL_INTERVAL = 0.2


def free_port() -> int:
    """A port on 127.0.0.1 that no process is listening on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(slug_dir: Path, port: int, repo_root: Path) -> subprocess.Popen[bytes]:
    """Start `server:app` from `slug_dir` with cwd = repo root, so a cwd-dependent server fails.

    `-B` keeps uvicorn from writing `__pycache__/` into the Write_Scope (Req 1.5).
    """
    return subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "uvicorn",
            "server:app",
            "--app-dir",
            str(slug_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def wait_ready(proc: subprocess.Popen[bytes], port: int, timeout: float = READY_TIMEOUT) -> None:
    """Return once the server sends any HTTP response; raise if it exits first or stays silent."""
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=1.0, trust_env=False) as client:
        while True:
            code = proc.poll()
            if code is not None:
                raise ReanimateError(
                    "check", f"Revenant_Server exited with code {code} before answering", 1
                )
            try:
                client.get(base_url(port) + "/")
                return
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise ReanimateError(
                    "check", f"Revenant_Server did not answer within {timeout:g} seconds", 1
                )
            time.sleep(POLL_INTERVAL)


def request(port: int, path: str, timeout: float = REQUEST_TIMEOUT) -> httpx.Response | None:
    """GET `path`; None when no response arrives within `timeout` seconds."""
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            return client.get(base_url(port) + path)
    except httpx.HTTPError:
        return None


def donor_header(entry: DonorEntry) -> str:
    return f"wayback:{entry.host}/{entry.served_timestamp}"


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _body_lines(body: bytes) -> list[bytes]:
    lines = body.split(b"\n")
    while lines and lines[-1] == b"":
        lines.pop()
    return lines


def _donor_line(donor_bytes: bytes, row_date: str) -> bytes | None:
    prefix = row_date.encode("ascii") + b","
    for line in donor_bytes.split(b"\n"):
        if line.startswith(prefix):
            return line
    return None


def _fail(expected: str, observed: str, name: CheckName = "demo") -> CheckResult:
    return CheckResult(name=name, result="fail", expected=expected, observed=observed)


def _no_response(name: CheckName, timeout: float) -> CheckResult:
    return _fail(f"a response within {timeout:g} seconds", "no response", name)


def eval_demo(
    response: httpx.Response | None,
    donor_entry: DonorEntry,
    donor_bytes: bytes,
    timeout: float = REQUEST_TIMEOUT,
) -> CheckResult:
    """Judge the demo response (Req 6.2). `response` is None when none arrived within 10 s."""
    if response is None:
        return _no_response("demo", timeout)
    if response.status_code != 200:
        return _fail("status 200", f"status {response.status_code}")
    media = _media_type(response)
    if media != "text/csv":
        return _fail("Content-Type text/csv", f"Content-Type {media or '(none)'}")
    lines = _body_lines(response.content)
    first = lines[0] if lines else b""
    if first != HEADER_LINE:
        return _fail(f"first line {HEADER_LINE!r}", f"first line {first!r}")
    rows = lines[1:]
    if len(rows) != len(DEMO_DATES):
        return _fail(f"{len(DEMO_DATES)} Data_Rows", f"{len(rows)} Data_Rows")
    for row, row_date in zip(rows, DEMO_DATES, strict=True):
        expected = _donor_line(donor_bytes, row_date)
        if expected is None:
            return _fail(f"donor line for {row_date}", "no such line in the AAPL Donor_Capture")
        if row != expected:
            return _fail(f"row {expected!r}", f"row {row!r}")
    want = donor_header(donor_entry)
    got = response.headers.get_list("x-revenant-donor")
    if got != [want]:
        return _fail(f"X-Revenant-Donor {want}", f"X-Revenant-Donor {got}")
    return CheckResult(name="demo", result="pass")


def unknown_symbol(known: Iterable[str]) -> str:
    """A symbol with no Donor_Capture: not in the Donor_Index (Req 6.3)."""
    taken = set(known)
    symbol = UNKNOWN_SYMBOL
    while symbol in taken:
        symbol += "X"
    return symbol


def unknown_path(symbol: str) -> str:
    """The demo request with `s` replaced by `symbol` (Req 6.3)."""
    return DEMO_PATH.replace("s=AAPL&", f"s={quote(symbol, safe='')}&", 1)


def eval_unknown(response: httpx.Response | None, timeout: float = REQUEST_TIMEOUT) -> CheckResult:
    """Req 6.3: an unknown symbol answers 404 with a `text/html` media type."""
    name: CheckName = "unknown_symbol"
    if response is None:
        return _no_response(name, timeout)
    if response.status_code != 404:
        return _fail("status 404", f"status {response.status_code}", name)
    media = _media_type(response)
    if media != "text/html":
        return _fail("Content-Type text/html", f"Content-Type {media or '(none)'}", name)
    return CheckResult(name=name, result="pass")


def eval_weekly(response: httpx.Response | None, timeout: float = REQUEST_TIMEOUT) -> CheckResult:
    """Req 6.4: `g=w` answers 404 with a non-empty `X-Revenant-Note`."""
    name: CheckName = "weekly"
    if response is None:
        return _no_response(name, timeout)
    if response.status_code != 404:
        return _fail("status 404", f"status {response.status_code}", name)
    note = response.headers.get("x-revenant-note", "").strip()
    if not note:
        return _fail("a non-empty X-Revenant-Note", "no X-Revenant-Note", name)
    return CheckResult(name=name, result="pass")


def not_run(name: CheckName) -> CheckResult:
    return CheckResult(name=name, result="not_run")


@dataclass(frozen=True)
class Limits:
    """Check time limits in seconds; tests pass short ones (Req 6.1, 6.2-6.5)."""

    ready: float = READY_TIMEOUT
    request: float = REQUEST_TIMEOUT
    stop: float = STOP_TIMEOUT


def run_checks(
    slug_dir: Path,
    repo_root: Path,
    index: DonorIndex,
    demo_symbol: str = "AAPL",
    limits: Limits | None = None,
) -> dict[str, CheckResult]:
    """Start the server, run demo then unknown_symbol and weekly, always stop it (Req 6.1-6.6).

    Every Check gets a result: a Check whose precondition did not hold is `not_run`.
    """
    limits = limits or Limits()
    results: dict[str, CheckResult] = {name: not_run(name) for name in CHECK_NAMES}
    entry = index.entries.get(demo_symbol)
    if entry is None:
        results["demo"] = _fail(f"an {demo_symbol} donor", "none")
        return results
    donor_bytes = (slug_dir / "donor" / entry.file).read_bytes()
    port = free_port()
    proc = serve(slug_dir.resolve(), port, repo_root.resolve())
    try:
        try:
            wait_ready(proc, port, limits.ready)
        except ReanimateError as exc:
            results["demo"] = _fail("server answering", exc.message)
            return results
        demo = eval_demo(
            request(port, DEMO_PATH, limits.request), entry, donor_bytes, limits.request
        )
        results["demo"] = demo
        if demo.result != "pass":
            return results
        symbol = unknown_symbol(index.entries)
        results["unknown_symbol"] = eval_unknown(
            request(port, unknown_path(symbol), limits.request), limits.request
        )
        results["weekly"] = eval_weekly(request(port, WEEKLY_PATH, limits.request), limits.request)
        return results
    finally:
        stop(proc, limits.stop)


def failures(results: dict[str, CheckResult]) -> list[str]:
    """One line per failed Check with its expected and observed value (Req 6.6)."""
    return [
        f"{name}: expected {result.expected}, observed {result.observed}"
        for name, result in results.items()
        if result.result == "fail"
    ]


def stop(proc: subprocess.Popen[bytes], timeout: float = STOP_TIMEOUT) -> None:
    """Stop the server, wait up to `timeout` seconds, then force-terminate (Req 6.5)."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            proc.kill()
    proc.wait()
