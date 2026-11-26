"""Import and path audit of a built `server.py` (Req 7.3, 7.4).

Violations: an import other than `fastapi`, `uvicorn` or the standard library, a relative import,
a string constant naming a path under `evidence/`, a `py_compile` error, and any Ruff_F_Check
finding (`ruff check --isolated --select F`). Style is not checked.
"""

from __future__ import annotations

import ast
import py_compile
import subprocess
import sys
import tempfile
from pathlib import Path

ALLOWED_THIRD_PARTY = frozenset({"fastapi", "uvicorn"})
EVIDENCE_MARKERS = ("evidence/", "evidence\\")
RUFF_TIMEOUT = 60


def _allowed(module: str) -> bool:
    top = module.split(".", 1)[0]
    return top in ALLOWED_THIRD_PARTY or top in sys.stdlib_module_names


def _ast_violations(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _allowed(alias.name):
                    found.append(f"line {node.lineno}: disallowed import `{alias.name}`")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                target = "." * node.level + (node.module or "")
                found.append(f"line {node.lineno}: relative import `{target}`")
            elif node.module and not _allowed(node.module):
                found.append(f"line {node.lineno}: disallowed import `{node.module}`")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str | bytes):
            value = node.value
            text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
            if any(marker in text for marker in EVIDENCE_MARKERS):
                found.append(f"line {node.lineno}: path under evidence/ in {text!r}")
    return found


def _compile_violation(server: Path) -> str | None:
    with tempfile.TemporaryDirectory(prefix="revenant-audit-") as tmp:
        try:
            py_compile.compile(str(server), cfile=str(Path(tmp) / "server.pyc"), doraise=True)
        except py_compile.PyCompileError as exc:
            return f"py_compile: {exc.msg.strip()}"
    return None


def _ruff_violations(server: Path) -> list[str]:
    argv = [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "F"]
    argv += ["--output-format", "concise", "--no-cache", str(server)]
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUFF_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"ruff F check could not run: {exc}"]
    if done.returncode == 0:
        return []
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    findings = [line for line in lines if line.startswith(str(server)) or ": F" in line]
    if done.returncode == 1 and findings:
        return [f"ruff F: {line}" for line in findings]
    detail = (done.stderr.strip() or done.stdout.strip() or "no output").splitlines()[-1]
    return [f"ruff F check failed (exit {done.returncode}): {detail}"]


def audit(server: Path) -> list[str]:
    """Every violation in `server`, each named; an empty list means the server passes."""
    violations: list[str] = []
    source = server.read_bytes()
    try:
        tree = ast.parse(source, filename=str(server))
    except SyntaxError as exc:
        violations.append(f"syntax error at line {exc.lineno}: {exc.msg}")
    else:
        violations.extend(_ast_violations(tree))
    compile_error = _compile_violation(server)
    if compile_error:
        violations.append(compile_error)
    violations.extend(_ruff_violations(server))
    return violations
