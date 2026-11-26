"""Post-build Check: run the Revenant_Server under uvicorn and test it (Req 6.1, 6.2, 6.5)."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.record import CheckResult, DonorEntry

HEADER_LINE = b"Date,Open,High,Low,Close,Volume,Adj Close"
DEMO_PATH = "/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv"
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
    """Start `server:app` from `slug_dir` with cwd = repo root, so a cwd-dependent server fails."""
    return subprocess.Popen(
        [
            sys.executable,
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


def _fail(expected: str, observed: str) -> CheckResult:
    return CheckResult(name="demo", result="fail", expected=expected, observed=observed)


def eval_demo(
    response: httpx.Response | None, donor_entry: DonorEntry, donor_bytes: bytes
) -> CheckResult:
    """Judge the demo response (Req 6.2). `response` is None when none arrived within 10 s."""
    if response is None:
        return _fail(f"a response within {REQUEST_TIMEOUT:g} seconds", "no response")
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
