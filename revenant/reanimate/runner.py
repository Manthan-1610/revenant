"""The Reanimate Runner: preflight, donors, prompt, headless build, demo Check (Req 1, 3, 4)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from revenant.autopsy.contract import Contract, contract_path, load_contract
from revenant.autopsy.render import spec_path
from revenant.exhume.archive import (
    ArchiveClient,
    Clock,
    RateLimiter,
    SystemClock,
    make_client,
    user_agent,
)
from revenant.exhume.models import Index, Tombstone, TombstoneError, load_tombstone
from revenant.exhume.store import EvidenceStore, atomic_write
from revenant.reanimate import build, check
from revenant.reanimate.donor import DonorReport, fetch_donors, load_donor_index
from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.kiro import CHAT_TIMEOUT, ChatResult, KiroCli
from revenant.reanimate.prompt import render_prompt, write_prompt
from revenant.reanimate.record import BuildPath, BuildRecord, CheckResult, dump_model

HEADLESS: BuildPath = "kiro-cli-headless"
IDE_CHAT: BuildPath = "kiro-ide-chat"
RECORD_NAME = "reanimate.json"
LOG_NAME = "reanimate.log"
DEMO_SYMBOL = "AAPL"
CHECK_NAMES = ("demo", "unknown_symbol", "weekly")
FALLBACKS = (
    "use --prompt-only and paste the prompt into Kiro IDE chat, then --built-by kiro-ide-chat"
)


@dataclass
class Deps:
    """Injected collaborators: tests pass the stub kiro-cli, a MockTransport and a tmp repo root."""

    kiro: KiroCli = field(default_factory=KiroCli)
    transport: httpx.BaseTransport | None = None
    clock: Clock = field(default_factory=SystemClock)
    repo_root: Path = Path(".")
    chat_timeout: float = CHAT_TIMEOUT


@dataclass
class Summary:
    """What a successful run did (Req 1.4)."""

    slug: str
    build_path: BuildPath
    stored: list[str]
    missing: dict[str, str]
    checks: dict[str, CheckResult | None]

    def lines(self) -> list[str]:
        missing = ", ".join(self.missing) or "none"
        out = [
            f"reanimate: {self.slug}",
            f"donors stored: {', '.join(self.stored) or 'none'}",
            f"donors missing: {missing}",
            f"build path: {self.build_path}",
        ]
        for name in CHECK_NAMES:
            result = self.checks.get(name)
            out.append(f"check {name}: {result.result if result else 'not_run'}")
        return out


@dataclass(frozen=True)
class _Inputs:
    tombstone: Tombstone
    contract: Contract
    spec: Path
    error_body: bytes


def _now(clock: Clock) -> str:
    return clock.now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _error_capture(root: Path, slug: str, contract: Contract) -> tuple[Path, bytes]:
    """Body of the newest archived 404 capture (Gen 7.1), checked against its Index SHA-256."""
    statuses = [error for error in contract.errors if error.status == "404"]
    if not statuses or not statuses[0].evidence.keys:
        raise ValueError("contract names no archived 404 capture")
    key = statuses[0].evidence.keys[0]  # keys are newest first
    store = EvidenceStore(root / "evidence", slug)
    entry = Index.model_validate_json(store.index_path.read_bytes()).entries.get(key)
    if entry is None:
        raise ValueError(f"{store.index_path.as_posix()}: no Index entry {key}")
    path = store.slug_dir / entry.path
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != entry.sha256:
        raise ValueError(f"{path.as_posix()}: SHA-256 does not match the Index")
    return path, body


def preflight(root: Path, slug: str) -> _Inputs:
    """Req 1.2: every input exists and validates; no network. Exit 2 naming each bad path."""
    problems: list[str] = []
    tombstone: Tombstone | None = None
    contract: Contract | None = None
    try:
        tombstone = load_tombstone(slug, root / "tombstones")
    except TombstoneError as exc:
        problems.append(str(exc))
    cpath = contract_path(root / "crypt", slug)
    try:
        contract = load_contract(cpath)
    except (OSError, ValueError) as exc:
        problems.append(f"{cpath.as_posix()}: missing or invalid contract ({type(exc).__name__})")
    spec = spec_path(root / ".kiro" / "specs", slug)
    if not spec.is_file():
        problems.append(f"{spec.as_posix()}: generated spec not found")
    error_body = b""
    if contract is not None:
        try:
            _, error_body = _error_capture(root, slug, contract)
        except (OSError, ValueError) as exc:
            problems.append(f"archived 404 capture (Gen 7.1): {exc}")
    else:
        problems.append("archived 404 capture (Gen 7.1): cannot be located without a contract")
    if problems or tombstone is None or contract is None:
        raise ReanimateError("preflight", "; ".join(problems), 2)
    return _Inputs(tombstone, contract, spec, error_body)


def kiro_preflight(kiro: KiroCli) -> str:
    """Req 3.3, 4.5, 4.6: kiro-cli on the PATH, logged in, and reporting a version."""
    if not kiro.available():
        raise ReanimateError("kiro", f"kiro-cli is not on the PATH; {FALLBACKS}", 2)
    if kiro.whoami() != 0:
        raise ReanimateError("kiro", f"kiro-cli whoami failed (no login?); {FALLBACKS}", 2)
    try:
        return kiro.version()
    except ReanimateError as exc:
        raise ReanimateError(
            "kiro", f"{exc.message}; use the IDE fallback --built-by kiro-ide-chat", 2
        ) from exc


def _donors(inputs: _Inputs, deps: Deps, slug_dir: Path) -> DonorReport:
    store = EvidenceStore(deps.repo_root / "evidence", inputs.tombstone.slug)
    with make_client(RateLimiter(deps.clock), user_agent(), deps.transport) as client:
        report = fetch_donors(inputs.tombstone, ArchiveClient(client, deps.clock), store, slug_dir)
    if report.required_missing:
        messages = "; ".join(report.missing[symbol] for symbol in report.required_missing)
        raise ReanimateError("donor", f"required donor missing: {messages}", 1)
    return report


def run_demo_check(slug_dir: Path, repo_root: Path) -> CheckResult:
    """Req 6.1, 6.2, 6.5: start uvicorn, send the demo request, stop the server."""
    index = load_donor_index(slug_dir, slug_dir.name)
    entry = index.entries.get(DEMO_SYMBOL)
    if entry is None:
        return CheckResult(name="demo", result="fail", expected="an AAPL donor", observed="none")
    donor_bytes = (slug_dir / "donor" / entry.file).read_bytes()
    port = check.free_port()
    proc = check.serve(slug_dir.resolve(), port, repo_root.resolve())
    try:
        try:
            check.wait_ready(proc, port)
        except ReanimateError as exc:
            return CheckResult(
                name="demo", result="fail", expected="server answering", observed=exc.message
            )
        return check.eval_demo(check.request(port, check.DEMO_PATH), entry, donor_bytes)
    finally:
        check.stop(proc)


def _write_record(
    slug_dir: Path,
    started: str,
    deps: Deps,
    prompt_bytes: bytes,
    version: str | None,
    chat: ChatResult | None,
    note: str | None,
    demo: CheckResult | None,
) -> None:
    record = BuildRecord(
        build_path=HEADLESS,
        prompt_sha256=hashlib.sha256(prompt_bytes).hexdigest(),
        kiro_version=version,
        kiro_exit_code=chat.exit_code if chat else None,
        timed_out=chat.timed_out if chat else False,
        note=note,
        model=chat.model if chat else None,
        started_at=started,
        ended_at=_now(deps.clock),
        checks={"demo": demo, "unknown_symbol": None, "weekly": None},
    )
    atomic_write(slug_dir / RECORD_NAME, dump_model(record))


def reanimate(slug: str, prompt_only: bool, built_by: str, deps: Deps) -> Summary:
    """Run every stage in order (Req 1.1); any failure raises ReanimateError with its exit code."""
    if prompt_only or built_by != HEADLESS:
        # Task 8 adds --prompt-only and --built-by kiro-ide-chat.
        raise ReanimateError("cli", "only the kiro-cli-headless build is implemented", 2)
    root = deps.repo_root
    inputs = preflight(root, slug)
    version = kiro_preflight(deps.kiro)
    slug_dir = root / "crypt" / slug
    atomic_write(slug_dir / build.ERROR_PAGE_NAME, inputs.error_body)  # Req 1.3
    report = _donors(inputs, deps, slug_dir)

    entries = load_donor_index(slug_dir, slug).entries.values()
    prompt = write_prompt(slug_dir, render_prompt(slug, entries))
    prompt_bytes = prompt.read_bytes()

    started = _now(deps.clock)
    workspace = build.make_workspace(slug_dir, inputs.spec)
    chat = deps.kiro.chat(workspace, slug_dir / LOG_NAME, timeout=deps.chat_timeout)
    failure: str | None = None
    if chat.timed_out:
        failure = f"kiro-cli was stopped after {deps.chat_timeout:g} seconds"
    elif chat.exit_code != 0:
        failure = f"kiro-cli exited with code {chat.exit_code}"
    elif not build.has_server(workspace):
        failure = "kiro-cli wrote no server"
    if failure is not None:
        _write_record(slug_dir, started, deps, prompt_bytes, version, chat, failure, None)
        raise ReanimateError("build", f"{failure}; workspace kept at {build.display(workspace)}")
    build.copy_back(workspace, slug_dir)

    demo = run_demo_check(slug_dir, root)
    _write_record(slug_dir, started, deps, prompt_bytes, version, chat, None, demo)
    if demo.result != "pass":
        raise ReanimateError(
            "check", f"demo failed: expected {demo.expected}, observed {demo.observed}"
        )
    return Summary(
        slug=slug,
        build_path=HEADLESS,
        stored=list(report.stored),
        missing=dict(report.missing),
        checks={"demo": demo, "unknown_symbol": None, "weekly": None},
    )
