# Implementation Plan: Reanimate

> The user approved the design; tasks may run in order.

## Overview

Python 3.12 implementation of `revenant reanimate <slug>`, following the modules in `design.md`
(`revenant/reanimate/{errors,record,donor,prompt,kiro,build,check,scope,audit,redact,runner}.py`, the Tombstone
change in `revenant/exhume/models.py` and the `reanimate` command in `revenant/cli.py`). The plan builds a thin
vertical slice first: by the end of task 4 a LIVE run has fetched the AAPL Donor_Capture through the Archive,
built `crypt/yahoo-finance-ichart/server.py` with a real `kiro-cli chat --v3 --no-interactive --trust-workspace
--trust-tools=fs_read,fs_write --output-format stream-json ...` headless run in a Build_Workspace, and passed the
demo Check (Req 6.2). Tasks 1 to 3 and the non-live parts of task 4 use only the stubbed kiro-cli
(`tests/reanimate/fake_kiro.py`). Tasks 5 to 9 harden the Runner (scope diff, import audit, redaction,
Build_Record, exit codes, IDE fallback, remaining Checks). Task 10 adds the optional donors and runs everything live.

Reused from Exhume and Autopsy, imported and never copied: `load_tombstone`, `Tombstone`, `CdxRow`,
`ArchiveClient`, `ArchiveError`, `RateLimiter`, `SystemClock`, `make_client`, `user_agent`, `get_listing`,
`wayback_url`, `served_timestamp`, `parse_query`, `interval`, `has_auth_param`, `EvidenceStore`, `atomic_write`
(`revenant.exhume`); `load_contract`, `contract_path`, `parse_body`, `parse_row_date` (`revenant.autopsy`).

Tests use pytest and Hypothesis in `tests/reanimate/`. Unit tests never touch the network: `httpx.MockTransport`
serves CDX listings and capture bodies from `evidence/` fixtures, `tests/reanimate/fake_kiro.py` stands in for
kiro-cli (`whoami`, `--version`, `chat`), and `KIRO_API_KEY` is removed with `monkeypatch` (Req 7.6). Sub-tasks
marked **(LIVE)** need the Archive or a real kiro-cli; their tests carry `@pytest.mark.live` and the default
`-m 'not live'` run skips them. Each property test uses `@settings(max_examples=100)` and the comment
`# Feature: reanimate, Property <n>: <title>`.

**Execution rules (every task):**
- After each task run `.venv\Scripts\ruff check .`, `.venv\Scripts\ruff format .` and
  `.venv\Scripts\python -m pytest`; all must pass.
- Commit with the message `reanimate: task N - <title>`.
- Each task report is at most 8 lines.
- If a test fails twice, stop and report instead of trying again.
- Never edit `victims/`, `.kiro/steering/` or anything under `evidence/`, except the CDX_Listing cache that
  Exhume's `get_listing` writes to `evidence/<slug>/cdx/`.

## Tasks

- [x] 1. Add the Tombstone donor fields and the Donor_Fetcher (`donor.py`)
  - [x] 1.1 Add the Tombstone fields, the error type and the donor models
    - In `revenant/exhume/models.py`: `donor_symbols: list[str] = []`, `donor_required: list[str] = []`, and a `model_validator(mode="after")` whose error names each `donor_required` symbol missing from `donor_symbols`; `extra="forbid"` stays
    - In `tombstones/yahoo-finance-ichart.toml`: `donor_symbols = ["AAPL"]`, `donor_required = ["AAPL"]` (task 10 adds the optional symbols)
    - Create `revenant/reanimate/__init__.py`, `errors.py` with `ReanimateError(stage, message, code)`, and `record.py` with `DonorEntry`, `DonorIndex` (`ConfigDict(extra="forbid", frozen=True)`) and `dump_model` (Exhume's `dump_index` recipe)
    - Create `tests/reanimate/__init__.py`
    - In `.gitattributes`: add `crypt/*/donor/** -text` and `crypt/*/error-404.html -text`, so clones keep donor and Error_Page bytes unchanged
    - _Requirements: 2.1, 2.4, 7.5_
  - [x] 1.2 Write example tests in `tests/reanimate/test_tombstone.py`
    - Absent fields load as empty lists; the committed tombstone loads; a `donor_required` symbol missing from `donor_symbols` raises an error naming it; Exhume's existing Tombstone tests still pass
    - _Requirements: 2.1_
  - [x] 1.3 Write the pure helpers `candidates`, `accept` and `donor_file_name`
    - `candidates(rows, symbol, mimetypes)`: status 2xx, listed mimetype, timestamp `< "20170501"`, no `has_auth_param`, first `s` of `parse_query(original)` equals `symbol` after percent-decoding, query `s_only` or Daily_Range (`interval == "d"`, `c` ASCII digits ≤ 1999, `f` absent, empty or digits ≥ timestamp year); sort by (timestamp desc, original asc); keep the first row per digest
    - `accept(body, served) -> str | None`: `None` when accepted, else the reason (served `< "20170501"`, first line exactly the Header_Line, ≥ 1 Data_Row via `parse_body`, newest Row_Date within 0..7 days before the served date)
    - `donor_file_name(symbol)`: keep `A-Z 0-9 . - _`, write every other UTF-8 byte as `%XX`, add `.csv` (`^GSPC` → `%5EGSPC.csv`)
    - _Requirements: 2.2, 2.3, 2.4_
  - [x] 1.4 Write property test P1 in `tests/reanimate/test_donor.py`
    - **Property 1: Donor candidate filter and order**: for any CDX rows (raw and `%5E` symbols, `&amp` artifacts, any status, mimetype, timestamp, auth-like names, repeated digests) and any symbol, every returned row meets each Req 2.2 condition, digests are unique, order is (timestamp desc, original asc), no qualifying digest is lost, and input order does not matter
    - **Validates: Requirements 2.2**
  - [x] 1.5 Write `fetch_donors` and `DonorReport`
    - `fetch_donors(tombstone, archive, store, slug_dir) -> DonorReport(stored, missing, required_missing)`: reuse a hash-valid Donor_Index entry with zero requests; else pool `get_listing(..., "data", refresh=False)` over every host, fetch at most 5 candidates via `archive.get(wayback_url(...))` (an `ArchiveError` counts as a tried non-qualifier), `atomic_write` the first accepted body unchanged to `crypt/<slug>/donor/<donor_file_name>`, replace the symbol's entry in `donor/index.json`
    - A symbol with no qualifier is reported missing with a message naming it; no entry or file is written and existing donor files stay unchanged
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6_
  - [x] 1.6 Write property test P2 in `tests/reanimate/test_donor.py`
    - **Property 2: Donor acceptance and the 5-try cap**: for any body, served timestamp and newest-Row_Date offset of -3 to 12 days, `accept` returns `None` exactly when Req 2.3 holds; for any sequence of candidate outcomes (qualifies, fails, `ArchiveError`) the fetcher makes `min(5, i + 1)` fetches for a first qualifier at index `i` (else `min(5, n)`) and stores its bytes unchanged as `donor_file_name(symbol)`, which uses only `A-Za-z0-9.-_%` and differs after case folding for distinct symbols
    - **Validates: Requirements 2.3, 2.4, 2.6**
  - [x] 1.7 Write example tests in `tests/reanimate/test_donor.py`
    - With `httpx.MockTransport` and an AAPL fixture body from `evidence/`: an accepted capture writes a Donor_Index entry with the `id_` URL, host, Served_Timestamp, SHA-256, row count, first and last dates; a second call makes zero requests; a corrupted donor file triggers a refetch; a missing optional symbol continues, a missing required symbol sets `required_missing`; nothing under `evidence/` except `cdx/` is written
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 2.2, 2.4, 2.5, 2.6, 7.6_

- [x] 2. Write the Reanimate_Prompt, the KiroCli wrapper and the Build_Workspace
  - [x] 2.1 Add the dependencies and `prompt.py`
    - Add `fastapi` and `uvicorn` to `pyproject.toml` dependencies and install them into `.venv`
    - `render_prompt(slug, donors) -> str` and `write_prompt(slug_dir, text)`: name inputs only by `requirements.md`, `contract.json`, `donor/index.json`, `error-404.html`; name `server.py` as the single file to write; state that no shell or command tool is available, so Kiro must not run, test or install anything and writes only `server.py`; state the Server rules of the design (Req 5 and 7.3), each followed by the Gen criteria it cites; replace any earlier prompt
    - _Requirements: 3.1, 7.3_
  - [x] 2.2 Write `kiro.py`, the stub `tests/reanimate/fake_kiro.py` and the fixture server
    - `KiroCli(command=["kiro-cli"])`: `available()` via `shutil.which` (or the stub's path), `whoami() -> int` with stdout discarded, `version() -> str` (30 s timeout), `chat(cwd, log, timeout=900) -> ChatResult(exit_code, timed_out, model)` running exactly `chat --v3 --no-interactive --trust-workspace --trust-tools=fs_read,fs_write --output-format stream-json "Read reanimate-prompt.md in this directory and follow it exactly."`; reader threads label lines `stdout: `/`stderr: ` and append them to the Build_Log as they arrive; `model` is the first model id a stream-json event reports, else `None` (never guessed); `chat` stdout/stderr and `version` output decode with `encoding="utf-8", errors="replace"` (Windows defaults to cp1252); on timeout `terminate()`, then `kill()`
    - `fake_kiro.py` handles `whoami`, `--version` and `chat`; by env `FAKE_KIRO_MODE` it copies `tests/reanimate/fixtures/server.py` into its cwd, exits non-zero, sleeps, or writes no server; it records its argv to a file named by env
    - `tests/reanimate/fixtures/server.py`: a hand-written server that follows the Server rules (Req 5), so Runner tests never depend on Kiro
    - _Requirements: 3.2, 3.4, 3.5, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.3, 7.6_
  - [x] 2.3 Write `build.py`
    - `make_workspace(slug_dir, spec_path)`: `tempfile.mkdtemp(prefix="revenant-build-")` holding copies of only the glossary files; `copy_back(workspace, slug_dir)` copies `server.py` byte for byte; `display(path)` replaces the Home_Path with `~`; delete the workspace on success, keep it on failure
    - _Requirements: 3.2, 3.5, 3.6_
  - [x] 2.4 Write example tests in `tests/reanimate/test_prompt.py`, `test_kiro.py` and `test_build.py`
    - Prompt names only relative file names and contains no absolute path; it states that no shell or command tool is available and only `server.py` may be written; every Server rule is followed by a Gen citation; stub argv equals the exact chat argv; the Build_Log labels every line by stream and is complete after a non-zero exit and after a short-timeout stop (partial output kept); `whoami` stdout appears nowhere; a stub emitting non-cp1252 bytes (e.g. `→`, `✓`, an invalid UTF-8 byte) on `chat` and `--version` neither raises nor loses the line; `ChatResult.model` equals the id from a stub stream-json event, and is `None` when no event reports one; the workspace holds only the listed files; copy-back is byte-identical and deletes the workspace; a failed build keeps it
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 7.2_

- [x] 3. Implement the Check runner (`check.py`) and the server properties
  - [x] 3.1 Write `check.py` and add `CheckResult` to `record.py`
    - `free_port()` (bind `127.0.0.1:0`); `serve(slug_dir, port)` runs `sys.executable -m uvicorn server:app --app-dir <slug_dir> --host 127.0.0.1 --port <p>` with cwd = repo root; `wait_ready` treats any HTTP response as answering, at most 30 s, and fails if the process exits first; pure `eval_demo(response, donor_entry, donor_bytes) -> CheckResult` (10 s timeout, status 200, `text/csv` media type, Header_Line, the five 2016-01-08..04 rows byte-equal to the donor lines, `X-Revenant-Donor` from the AAPL entry); `stop(proc)` waits 10 s, then kills
    - _Requirements: 6.1, 6.2, 6.5_
  - [x] 3.2 Write example tests in `tests/reanimate/test_check.py`
    - Copy `fixtures/server.py` beside a fixture `donor/` and `error-404.html` in `tmp_path`, start it with `serve`, and assert the demo Check passes; `eval_demo` fails with expected and observed values for a wrong status, a reformatted row, a missing row and a wrong donor header; the process has exited after `stop`
    - _Requirements: 6.1, 6.2, 6.5_
  - [x] 3.3 Write property test P5 in `tests/reanimate/test_server.py`
    - **Property 5: Served rows equal donor lines in range**: for any fixture donor (random newest-first trading days, Yahoo_Number values, `000` volumes) and any Daily_Request whose `a`–`f` mix in-range ints, 12, out-of-range ints, day 31, empty, absent and junk such as `{{(-1 month).year}}`, with raw or percent-encoded `s`, `server.py` answers as a reference selector predicts: 200 with the Header_Line and exactly the in-range donor lines, byte-equal, newest first; else 404 + Error_Page
    - Load `crypt/<slug>/server.py` (fall back to `fixtures/server.py` before the slice build exists) from `tmp_path` with `importlib`, drive it with `fastapi.testclient.TestClient`
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
  - [x] 3.4 Write property test P6 in `tests/reanimate/test_server.py`
    - **Property 6: Donor header and interval gate**: for any request the response has exactly one `X-Revenant-Donor`, equal to `wayback:<host>/<served_timestamp>` when `s` has a donor and `none` otherwise; for any non-empty `g` other than `d`, whatever `s` is, the status is 404 with a non-empty `X-Revenant-Note`
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - **Validates: Requirements 5.5, 5.6**

- [x] 4. Wire the minimal Runner and CLI, then run the slice live
  - [x] 4.1 Write the happy path in `runner.py`, a minimal `BuildRecord` and the CLI command
    - `reanimate(slug, prompt_only, built_by, deps: Deps) -> Summary`: file preflight (Tombstone, Contract, Generated_Spec, archived 404 capture; exit 2 naming each path, no network); kiro-cli preflight (`available`, `whoami`, `version`; exit 2); copy the 404 body to `error-404.html`; `fetch_donors` (exit 1 on a missing required symbol); `write_prompt`; `make_workspace` → `chat` → `copy_back`; demo Check; write `reanimate.json` with Build_Path, kiro version, exit code, `model: str | None` (from `ChatResult.model`), times and the demo result; print the summary; `ReanimateError` → `error: <stage>: <message>` on stderr with its exit code
    - Typer command `reanimate(slug, prompt_only=False, built_by="kiro-cli-headless")` beside `autopsy` in `revenant/cli.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 3.3, 4.4, 4.5_
  - [x] 4.2 Write happy-path tests in `tests/reanimate/test_runner.py`
    - With `MockTransport`, the stub kiro-cli and a `tmp_path` repo copy: exit 0, stages run in order, `server.py`, `donor/`, `error-404.html` (byte-equal to the archived 404), `reanimate-prompt.md`, `reanimate.json` and `reanimate.log` are written, evidence files outside `cdx/` are unchanged; a missing Contract exits 2 before any request; a stub chat exiting 1 exits 1 with no Check
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 7.6_
  - [x] 4.3 (LIVE) Fetch the AAPL donor through the Archive
    - Write `tests/reanimate/test_live.py::test_live_aapl_donor` with `@pytest.mark.live`: real `ArchiveClient`, `fetch_donors` for AAPL into `tmp_path`, assert an accepted capture covering 2016-01-04..08 (F18)
    - Run `.venv\Scripts\python -m pytest -m live -k aapl_donor`; it must pass
    - _Requirements: 2.2, 2.3, 2.4, 7.6_
  - [x] 4.4 (LIVE) Build the server with real kiro-cli headless and pass the demo Check
    - Requires the user to be logged in: run `kiro-cli whoami`; if it exits non-zero, stop and ask the user to log in before continuing
    - Run `.venv\Scripts\revenant reanimate yahoo-finance-ichart` from the repo root; confirm exit 0, `crypt/yahoo-finance-ichart/server.py` written by the real `kiro-cli chat --v3 --no-interactive --trust-workspace --trust-tools=fs_read,fs_write --output-format stream-json ...` run in a Build_Workspace, the demo Check passes and `reanimate.json` records `kiro-cli-headless` and `model` (an id or null)
    - If kiro-cli fails (non-zero exit, timeout or no `server.py`), report its exit code and the last 20 Build_Log lines; retry at most once, and if the retry also fails, STOP and report
    - Write `tests/reanimate/test_live.py::test_live_build` with `@pytest.mark.live` for the same flow; then run the default suite so P5 and P6 run against the built `server.py`; if a property fails, fix the prompt and rebuild (never hand-edit `server.py`)
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 3.2, 3.6, 4.4, 4.5, 6.1, 6.2, 7.6_

- [ ] 5. Add the scope diff (`scope.py`) and the import audit (`audit.py`)
  - [ ] 5.1 Write `scope.py` and add `ScopeChange` to `record.py`
    - `snapshot(root, exclude) -> dict[str, str]` (POSIX path → SHA-256) skips the Build_Log, the root-level `.git/`, `.venv/`, `.hypothesis/`, `.pytest_cache/`, `.ruff_cache/`, and any `__pycache__/` at any depth; `diff(before, after) -> list[ScopeChange]` in path order
    - _Requirements: 7.1_
  - [ ] 5.2 Write property test P4 in `tests/reanimate/test_scope.py`
    - **Property 4: Scope diff is exact**: for any snapshot and any set of creations, changes and deletions applied to it, `diff` returns exactly those paths with their change types in path order, and an empty list when nothing changed
    - Example tests in the same file: a change under each excluded location (`.git/`, `.venv/`, `.hypothesis/`, `.pytest_cache/`, `.ruff_cache/`, a nested `__pycache__/`, the Build_Log) yields no change; a change to any other file (including a nested `.venv/` that is not at root) is still reported
    - **Validates: Requirements 7.1**
  - [ ] 5.3 Write `audit.py`
    - `audit(server) -> list[str]` via `ast`: imports must be `fastapi`, `uvicorn` or in `sys.stdlib_module_names`; relative imports and string constants containing `evidence/` or `evidence\` are violations, each named
    - Also run `py_compile` on `server.py` and the Ruff_F_Check `sys.executable -m ruff check --isolated --select F <server.py>`; a compile error or any finding is a violation, named in the list (exit 1 via the Runner). Style is not checked (`crypt/*/server.py` stays in `extend-exclude`, `pyproject.toml` line 42)
    - In `prompt.py`, add the line "Python 3.12 style: `X | None`, f-strings." to the Reanimate_Prompt
    - _Requirements: 3.1, 7.3, 7.4_
  - [ ] 5.4 Wire scope and audit into `runner.py` and write tests in `test_audit.py` and `test_runner.py`
    - Snapshot immediately before `chat` and after it exits or is stopped, before `copy_back`; any change → list each path with its change type, record it, leave files as they are, skip the Check, exit 1; audit after `copy_back` → record violations, skip the Check, exit 1
    - Tests: a stub mode that writes a file in the repo and one that deletes one; audit cases for `requests`, `httpx`, a relative import, an `evidence/` string, a syntax error (`py_compile`), an undefined name (Ruff_F_Check), a style-only issue that passes, and the fixture server passing; the prompt contains the Python 3.12 style line
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 3.1, 7.1, 7.3, 7.4_

- [ ] 6. Add redaction (`redact.py`)
  - [ ] 6.1 Write `Redactor(api_key, home)`
    - Replace the `KIRO_API_KEY` value (when set and non-empty), then every Email_Like_String, with `[REDACTED]`; then each Home_Path spelling (native, forward-slash, JSON-escaped, percent-encoded such as `c%3A/Users/<name>` and `C%3A%5CUsers%5C<name>`), longest first, drive letter case-insensitive, with `~`
    - The `Redactor` docstring documents the accepted over-redaction: the email pattern also matches `n@app.get` in an escaped `\n@app.get`
    - _Requirements: 7.2_
  - [ ] 6.2 Write property test P3 in `tests/reanimate/test_redact.py`
    - **Property 3: Redaction removes every secret**: for any text embedding a key (16+ characters, not a substring of `[REDACTED]` or `~`), Email_Like_Strings and the Home_Path in every spelling (native, forward-slash, JSON-escaped, percent-encoded with `/` or `%5C` separators, drive letter in either case), the output contains none of them, and redacting twice equals redacting once
    - **Validates: Requirements 7.2**
  - [ ] 6.3 Apply the Redactor everywhere and test it end to end
    - Redact the Reanimate_Prompt, each Build_Log line, the Build_Record and all console output; keep `whoami` stdout discarded
    - Add a `FAKE_KIRO_MODE` that prints a fake key (also set as `KIRO_API_KEY` via `monkeypatch`), a fake email such as `ghost@example.invalid` and a fake home path in native, forward-slash, JSON-escaped and percent-encoded (`file:///c%3A/Users/<name>/...`) spellings on `whoami`, `--version` and `chat`; assert none appears in any Write_Scope file or captured console output
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 7.2, 7.6_

- [ ] 7. Complete the Build_Record and the exit-code mapping
  - [ ] 7.1 Complete `BuildRecord` and the failure paths in `runner.py`
    - Fields: `build_path`, `prompt_sha256` (bytes on disk after redaction), `kiro_version`, `kiro_exit_code`, `timed_out`, `note`, `model: str | None` (from `ChatResult.model`; null for `kiro-ide-chat`; in `kiro.py`, `find_model(events)` returns the first `model`, `modelId` or `model_id` value an event reports, else the `currentValue` of the first `configOptions` entry with `id == "model"` (e.g. `"auto"` from `config_option_update`), else `None`; never guessed), `started_at`/`ended_at` (ISO 8601 UTC with `Z`), `scope_changes`, `import_violations`, `checks` (null per Check that did not run); write it after every finished build: exit 0, non-zero, 15-minute stop, and no `server.py` ("kiro-cli wrote no server")
    - `kiro-cli` not on PATH or `whoami` non-zero → message naming the prerequisite and the `--prompt-only` / `--built-by kiro-ide-chat` fallbacks, exit 2; `--version` non-zero, empty or > 30 s → name the IDE fallback, exit 2; kiro failure → print the kept workspace path via `display`, no success message, exit 1
    - _Requirements: 3.3, 3.5, 4.4, 4.5, 4.6, 1.6_
  - [ ] 7.2 Write exit-code tests in `tests/reanimate/test_runner.py`
    - One test per row of the design's Error Handling table with the stub modes (not on PATH, whoami fails, version fails/empty/slow, chat non-zero, timeout with a short limit, no server.py, required donor missing); each asserts the exit code, that no later stage ran, the Build_Record contents where one is written, and that the kept workspace path starts with `~` when under the home directory
    - `find_model` examples in `tests/reanimate/test_kiro.py`: a `model`/`modelId`/`model_id` key wins over `configOptions`; a `config_option_update` event with `{"id": "model", "currentValue": "auto"}` yields `"auto"`; no such data yields `None`
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 1.2, 1.5, 1.6, 3.3, 3.5, 4.4, 4.6_

- [ ] 8. Add the IDE fallback options
  - [ ] 8.1 Implement `--prompt-only` and `--built-by kiro-ide-chat` in `runner.py` and `revenant/cli.py`
    - `--prompt-only`: Donor_Fetcher, write the prompt, print its path, exit 0; no kiro-cli check, no Check
    - `--built-by kiro-ide-chat`: Donor_Fetcher, no kiro-cli invocation or check, no Build_Workspace, existing prompt and `server.py` unchanged, Check with Build_Path `kiro-ide-chat` and null kiro version and exit code; if `server.py` or the prompt is missing, name each, run no Check, write no Build_Record, exit 2
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [ ] 8.2 Write tests in `tests/reanimate/test_runner.py`
    - `--prompt-only` passes with no kiro-cli on PATH; `--built-by kiro-ide-chat` leaves `server.py` and the prompt byte-identical and records `kiro-ide-chat`; each missing-file case exits 2 with no `reanimate.json` written; `--help` lists both options
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 4.1, 4.2, 4.3_

- [ ] 9. Complete the Check cases
  - [ ] 9.1 Add `eval_unknown`, `eval_weekly` and the Check sequence to `check.py` and `runner.py`
    - Unknown-symbol Check: demo request with an `s` that has no Donor_Capture → 404 and `text/html` within 10 s; weekly Check: `g=w` → 404 with a non-empty `X-Revenant-Note`; both run only after the demo Check passes
    - At the end of the sequence (all run, demo failed, or 30-s wait expired) stop the server, confirm exit within 10 s, force-terminate otherwise; print each failed Check with expected and observed values, record pass, fail or not_run for every Check, no success message, exit 1
    - _Requirements: 6.3, 6.4, 6.5, 6.6_
  - [ ] 9.2 Write tests in `tests/reanimate/test_check.py` with misbehaving fixture servers
    - Fixture variants under `tests/reanimate/fixtures/`: one that never answers (short wait limit in the test), one that exits on import, one that returns 200 for an unknown symbol, one without `X-Revenant-Note`, one that ignores SIGTERM-style stop; assert the recorded results, the printed expected/observed values, exit 1 and that no server process remains
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.6_

- [ ] 10. Add the optional donors, commit the outputs and run end to end
  - [ ] 10.1 Add the optional symbols and the gitignore smoke test
    - In `tombstones/yahoo-finance-ichart.toml`: `donor_symbols = ["AAPL", "MSFT", "^GSPC", "YHOO"]`, `donor_required = ["AAPL"]`
    - Write `tests/reanimate/test_gitignore.py`: `git check-ignore` reports none of `crypt/yahoo-finance-ichart/{server.py,donor/index.json,error-404.html,reanimate-prompt.md,reanimate.json,reanimate.log}` as ignored, and `git check-attr text` reports `unset` for `crypt/yahoo-finance-ichart/donor/AAPL.csv` and `crypt/yahoo-finance-ichart/error-404.html` (the `.gitattributes` lines from task 1.1)
    - _Requirements: 2.1, 2.6, 7.5_
  - [ ] 10.2 (LIVE) Final end-to-end run
    - Requires `kiro-cli whoami` to exit 0; if it fails, stop and ask the user to log in
    - Run `.venv\Scripts\revenant reanimate yahoo-finance-ichart`; confirm exit 0, MSFT, `^GSPC` (stored as `%5EGSPC.csv`) and YHOO each stored or reported missing, AAPL reused with zero Archive requests, all three Checks pass, `reanimate.json` complete
    - kiro-cli is now 3.6.2: if its build fails on a flag (or otherwise: non-zero exit, timeout or no `server.py`), apply the 4.4 stop rule: report the exit code and the last 20 Build_Log lines, retry at most once, and if the retry also fails, STOP and report
    - The rebuild must leave a redacted `reanimate.log`: `git grep -i -c "<home dir name>" -- crypt/` returns nothing (no home path in any spelling, percent-encoded included); never edit `victims/`
    - Run `.venv\Scripts\python -m pytest -m live` (tests carry `@pytest.mark.live`) and the default suite; show the summary, the Build_Record and `curl -i` of the demo request against `uvicorn` on the built server
    - Commit the Write_Scope outputs under `crypt/yahoo-finance-ichart/` with the task commit
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 1.4, 2.5, 2.6, 3.5, 6.2, 6.3, 6.4, 7.2, 7.5_

## Notes

- The user approved the design; tasks run in order and commit per the execution rules.
- Execution rules from the Overview apply to every task: ruff check, ruff format and pytest after each task; commit as `reanimate: task N - <title>`; reports of at most 8 lines; stop and report after a test fails twice.
- Property tests P1 to P6 are required sub-tasks placed next to their components (tasks 1, 3, 5, 6); none are marked optional.
- Sub-tasks marked (LIVE) need the Archive or a real kiro-cli and their tests carry `@pytest.mark.live`; everything else runs offline with `httpx.MockTransport` and `tests/reanimate/fake_kiro.py`.
- Live kiro-cli steps (4.4, 10.2) require a stored login: `kiro-cli whoami` must exit 0. If it fails, the stage pauses for the user.
- `server.py` is written only by Kiro (headless, or IDE chat via `--built-by kiro-ide-chat`). To change server behaviour, change the prompt or contract and rebuild.
- Never edit `victims/`, `.kiro/steering/` or `evidence/`, except the CDX_Listing cache that `get_listing` writes.
- Open item from the design: whether `kiro-cli whoami` exits non-zero without a login (confirm during 4.4).
- Decisions after the first build (commit 37130d0) are folded into tasks 5.3, 5.4, 6.1–6.3, 7.1, 7.2 and 10.2: audit adds `py_compile` and the Ruff_F_Check, the prompt adds the Python 3.12 style line, `find_model` falls back to `configOptions`, the Redactor covers percent-encoded home paths, and kiro-cli 3.6.2 follows the 4.4 stop rule.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["1.4", "1.5", "2.2", "2.3"] },
    { "id": 3, "tasks": ["1.6", "2.4", "3.1"] },
    { "id": 4, "tasks": ["1.7", "3.2", "3.3"] },
    { "id": 5, "tasks": ["3.4", "4.1"] },
    { "id": 6, "tasks": ["4.2"] },
    { "id": 7, "tasks": ["4.3"] },
    { "id": 8, "tasks": ["4.4"] },
    { "id": 9, "tasks": ["5.1", "5.3", "6.1"] },
    { "id": 10, "tasks": ["5.2", "5.4", "6.2"] },
    { "id": 11, "tasks": ["6.3"] },
    { "id": 12, "tasks": ["7.1"] },
    { "id": 13, "tasks": ["7.2"] },
    { "id": 14, "tasks": ["8.1"] },
    { "id": 15, "tasks": ["8.2"] },
    { "id": 16, "tasks": ["9.1"] },
    { "id": 17, "tasks": ["9.2", "10.1"] },
    { "id": 18, "tasks": ["10.2"] }
  ]
}
```
