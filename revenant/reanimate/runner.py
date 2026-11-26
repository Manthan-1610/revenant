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
from revenant.reanimate import build, check, scope
from revenant.reanimate.audit import audit
from revenant.reanimate.donor import DonorReport, fetch_donors, load_donor_index
from revenant.reanimate.errors import ReanimateError
from revenant.reanimate.kiro import CHAT_TIMEOUT, ChatResult, KiroCli
from revenant.reanimate.prompt import PROMPT_NAME, render_prompt, write_prompt
from revenant.reanimate.record import (
    BuildPath,
    BuildRecord,
    CheckResult,
    ScopeChange,
    dump_model,
)
from revenant.reanimate.redact import Redactor

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
    redactor: Redactor = field(default_factory=Redactor.from_env)  # Req 7.2


@dataclass
class Summary:
    """What a successful run did (Req 1.4)."""

    slug: str
    build_path: BuildPath
    stored: list[str]
    missing: dict[str, str]
    checks: dict[str, CheckResult | None]
    prompt: str | None = None  # set by --prompt-only (Req 4.1): repo-relative prompt path

    def lines(self) -> list[str]:
        missing = ", ".join(self.missing) or "none"
        out = [
            f"reanimate: {self.slug}",
            f"donors stored: {', '.join(self.stored) or 'none'}",
            f"donors missing: {missing}",
        ]
        if self.prompt is not None:
            return [*out, f"prompt: {self.prompt}"]
        out.append(f"build path: {self.build_path}")
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


def audit_server(server: Path, repo_root: Path) -> list[str]:
    """Req 7.4: audit violations with the absolute server path replaced by its repo-relative one."""
    violations = audit(server)
    try:
        rel = server.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel = server.name
    spellings = {str(server), server.as_posix(), str(server.resolve()), server.resolve().as_posix()}
    cleaned: list[str] = []
    for violation in violations:
        for spelling in sorted(spellings, key=len, reverse=True):
            violation = violation.replace(spelling, rel)
        cleaned.append(violation)
    return cleaned


def _write_record(
    slug_dir: Path,
    started: str,
    deps: Deps,
    prompt_bytes: bytes,
    version: str | None,
    chat: ChatResult | None,
    note: str | None,
    demo: CheckResult | None,
    scope_changes: list[ScopeChange] | None = None,
    import_violations: list[str] | None = None,
    build_path: BuildPath = HEADLESS,
) -> None:
    red = deps.redactor  # Req 7.2: redact each string before JSON encoding, then the whole text
    record = BuildRecord(
        scope_changes=scope_changes or [],
        import_violations=[red(violation) for violation in import_violations or []],
        build_path=build_path,
        prompt_sha256=hashlib.sha256(prompt_bytes).hexdigest(),
        kiro_version=red(version) if version is not None else None,
        kiro_exit_code=chat.exit_code if chat else None,
        timed_out=chat.timed_out if chat else False,
        note=red(note) if note is not None else None,
        model=red(chat.model) if chat and chat.model else None,
        started_at=started,
        ended_at=_now(deps.clock),
        checks={"demo": demo, "unknown_symbol": None, "weekly": None},
    )
    # Req 7.2: the redacted spellings keep the JSON valid (JSON-escaped Home_Path included).
    text = deps.redactor(dump_model(record).decode("utf-8"))
    atomic_write(slug_dir / RECORD_NAME, text.encode("utf-8"))


def _summary(
    slug: str,
    build_path: BuildPath,
    report: DonorReport,
    demo: CheckResult | None = None,
    prompt: str | None = None,
) -> Summary:
    return Summary(
        slug=slug,
        build_path=build_path,
        stored=list(report.stored),
        missing=dict(report.missing),
        checks={"demo": demo, "unknown_symbol": None, "weekly": None},
        prompt=prompt,
    )


def _ide_chat_files(slug_dir: Path, slug: str) -> None:
    """Req 4.3: the IDE-built server and the prompt it was built from must both exist."""
    missing = [
        f"crypt/{slug}/{name}"
        for name in (build.SERVER_NAME, PROMPT_NAME)
        if not (slug_dir / name).is_file()
    ]
    if missing:
        raise ReanimateError(
            "ide-chat", "missing file(s) for --built-by kiro-ide-chat: " + ", ".join(missing), 2
        )


def _check_ide_build(slug: str, deps: Deps, inputs: _Inputs, slug_dir: Path) -> Summary:
    """Req 4.2, 4.4: audit and Check the IDE-built server; prompt and server.py stay unchanged."""
    report = _donors(inputs, deps, slug_dir)
    started = _now(deps.clock)
    prompt_bytes = (slug_dir / PROMPT_NAME).read_bytes()
    violations = audit_server(slug_dir / build.SERVER_NAME, deps.repo_root)  # Req 7.4
    if violations:
        note = "server.py failed the import audit"
        _write_record(
            slug_dir,
            started,
            deps,
            prompt_bytes,
            None,
            None,
            note,
            None,
            None,
            violations,
            IDE_CHAT,
        )
        raise ReanimateError("audit", f"{note}: " + "; ".join(violations))
    demo = run_demo_check(slug_dir, deps.repo_root)
    _write_record(
        slug_dir, started, deps, prompt_bytes, None, None, None, demo, build_path=IDE_CHAT
    )
    if demo.result != "pass":
        raise ReanimateError(
            "check", f"demo failed: expected {demo.expected}, observed {demo.observed}"
        )
    return _summary(slug, IDE_CHAT, report, demo=demo)


def reanimate(slug: str, prompt_only: bool, built_by: str, deps: Deps) -> Summary:
    """Run every stage in order (Req 1.1); any failure raises ReanimateError with its exit code."""
    if built_by not in (HEADLESS, IDE_CHAT):
        raise ReanimateError(
            "cli", f"--built-by must be {HEADLESS} or {IDE_CHAT}, not {built_by!r}", 2
        )
    if prompt_only and built_by == IDE_CHAT:
        raise ReanimateError(
            "cli", "--prompt-only and --built-by kiro-ide-chat exclude each other", 2
        )
    root = deps.repo_root
    inputs = preflight(root, slug)
    slug_dir = root / "crypt" / slug
    if built_by == IDE_CHAT:
        _ide_chat_files(slug_dir, slug)  # Req 4.3: before any network, Check or Build_Record
    version = None if prompt_only or built_by == IDE_CHAT else kiro_preflight(deps.kiro)
    atomic_write(slug_dir / build.ERROR_PAGE_NAME, inputs.error_body)  # Req 1.3
    if built_by == IDE_CHAT:
        return _check_ide_build(slug, deps, inputs, slug_dir)  # Req 4.2: prompt not rewritten
    report = _donors(inputs, deps, slug_dir)

    entries = load_donor_index(slug_dir, slug).entries.values()
    prompt = write_prompt(slug_dir, deps.redactor(render_prompt(slug, entries)))  # Req 7.2
    if prompt_only:  # Req 4.1: no kiro-cli, no build, no Check
        return _summary(slug, HEADLESS, report, prompt=f"crypt/{slug}/{PROMPT_NAME}")
    prompt_bytes = prompt.read_bytes()

    started = _now(deps.clock)
    workspace = build.make_workspace(slug_dir, inputs.spec)
    log_rel = f"crypt/{slug}/{LOG_NAME}"
    before = scope.snapshot(root.resolve(), exclude=(log_rel,))  # Req 7.1
    chat = deps.kiro.chat(
        workspace, slug_dir / LOG_NAME, timeout=deps.chat_timeout, redactor=deps.redactor
    )
    changes = scope.diff(before, scope.snapshot(root.resolve(), exclude=(log_rel,)))
    if changes:
        listed = ", ".join(f"{change.path} ({change.change})" for change in changes)
        note = f"kiro-cli changed repository files: {listed}"
        _write_record(slug_dir, started, deps, prompt_bytes, version, chat, note, None, changes)
        raise ReanimateError("scope", f"{note}; workspace kept at {build.display(workspace)}")
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

    violations = audit_server(slug_dir / build.SERVER_NAME, root)  # Req 7.4
    if violations:
        note = "server.py failed the import audit"
        _write_record(
            slug_dir, started, deps, prompt_bytes, version, chat, note, None, None, violations
        )
        raise ReanimateError("audit", f"{note}: " + "; ".join(violations))

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
