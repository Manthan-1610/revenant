# Implementation Plan: Exhume

## Overview

Python 3.12 implementation of `revenant exhume`, following the modules in `design.md`
(`revenant/exhume/{models,archive,cdx,store,content,ethics,select,run}.py` and `revenant/cli.py`).
The plan builds a thin vertical slice first: by the end of task 5 a live command downloads at least
one real capture for `ichart.yahoo.com`, using a naive "first N rows" pick. Later tasks add content
checks, the ethics filter, deterministic selection, backfill and caching, the error pass and the
Run_Summary. The live smoke test is the final task.

Tests use pytest and Hypothesis. Non-live tests use `httpx.MockTransport`, a `FakeClock` whose `sleep`
advances time without waiting, and `tmp_path` as Evidence_Root. Fixtures live in
`tests/exhume/fixtures/`. Each property test uses `@settings(max_examples=100)` and the comment
`# Feature: exhume, Property <n>: <title>`.

## Tasks

- [x] 1. Scaffold the project, install it and make `revenant --help` work
  - [x] 1.1 Write the minimal packaging, package skeleton, test layout and Tombstone
    - Write root `pyproject.toml`: hatchling build backend, `requires-python = ">=3.12"`, dependencies `httpx`, `pydantic>=2`, `typer`, `rich`; optional `dev` group `pytest`, `hypothesis`, `ruff`; console script `revenant = "revenant.cli:main"`
    - In `[tool.pytest.ini_options]` set `addopts = "-m 'not live'"`, `testpaths = ["tests"]` and register the `live` marker
    - Create `revenant/__init__.py` and subpackages `exhume`, `autopsy`, `reanimate`, `pulse`, `haunt`, `api`, each with an empty `__init__.py`
    - Write `revenant/cli.py` with `app = typer.Typer()`, a no-op `@app.callback()`, a stub `exhume(slug, --max-captures, --evidence-dir, --refresh)` command that prints "not implemented" and `main()` calling `app()`
    - Create `tests/__init__.py` if needed, `tests/exhume/__init__.py`, `tests/exhume/fixtures/` and `tests/exhume/test_cli.py` with one `CliRunner` test asserting `--help` exits 0 and lists `exhume`
    - Write `tombstones/yahoo-finance-ichart.toml` with the six fields of Req 1.5
    - Check `.gitignore`: it must not ignore `.kiro/`, `evidence/<slug>/index.json` or capture files; add `evidence/*/cdx/` and `.venv/`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_
  - [x] 1.2 Create the virtual environment, install and verify
    - First command-line step: `python -m venv .venv` at the repo root, then `.venv\Scripts\python -m pip install -e ".[dev]"`
    - Verify `.venv\Scripts\revenant --help` exits 0 and lists `exhume`
    - Verify `.venv\Scripts\python -m pytest` exits 0
    - _Requirements: 1.2, 1.4_

- [x] 2. Implement the data models and the Tombstone loader (`models.py`)
  - [x] 2.1 Write the models and `load_tombstone`
    - Define `PassKind`, `Kind`, `Shape`, `Tombstone` (`extra="forbid"`, non-empty lists, Hosts lowercased by a field validator), `CdxRow` (frozen), `Listing`, `IndexEntry`, `Index`, `HostSummary`, `RunResult` as in the design's Data Models
    - Implement `load_tombstone(slug, root=Path("tombstones"))` with `tomllib`; raise `TombstoneError` naming the file and failing fields for a missing file, invalid TOML, validation errors and a slug/file-name mismatch (naming both values)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 2.2 Write example tests in `tests/exhume/test_models.py`
    - Valid Tombstone loads; missing field, extra field, empty list, bad TOML, missing file and slug mismatch raise `TombstoneError` with the file name and field names; Hosts are lowercased
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 3. Implement the polite Archive client (`archive.py`)
  - [ ] 3.1 Write Clock, RateLimiter, User-Agent and client factory
    - `Clock` protocol and `SystemClock`; `FakeClock` in `tests/exhume/conftest.py` (sleep advances monotonic and UTC time, records start times)
    - `user_agent()` from env `REVENANT_USER_AGENT`, default `Revenant/0.1 (+https://github.com/Manthan-1610/revenant)`
    - `RateLimiter(clock, min_interval=1.0).on_request(request)` sleeping through `clock.sleep` only
    - `make_client(limiter, ua, transport=None)`: sync `httpx.Client`, `follow_redirects=True`, `event_hooks={"request": [limiter.on_request]}`, `httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)`, exactly one `User-Agent` header
    - _Requirements: 6.1, 6.5, 6.6_
  - [ ] 3.2 Write retry and backoff in `ArchiveClient.get`
    - `parse_retry_after(value, now)` for integer seconds and HTTP dates, 0 when absent or unparseable
    - `backoff_delay(attempt, retry_after) = min(60, max(2 * 2**(attempt-1), retry_after))`
    - `ArchiveClient(client, clock).get(url, params)`: retry connection errors, timeouts, 429 and 5xx up to 5 attempts in total, sleeping via the Clock; return any other response including non-429 4xx without retry; raise `ArchiveError` when attempts run out. Offline-page retry is added in task 6.2
    - _Requirements: 6.2, 6.3, 6.4, 6.6_
  - [ ] 3.3 Write property test P4 in `tests/exhume/test_archive.py`
    - **Property 4: Rate limiter spacing**: for any generated sequence of mocked responses (200, 429 with and without `Retry-After`, 5xx, connection errors, and the F6 302 redirect) under `FakeClock`, every pair of recorded request starts is at least 1 s apart, including retries and redirect hops
    - **Validates: Requirements 6.1**
  - [ ] 3.4 Write example tests for retry and headers in `tests/exhume/test_archive.py`
    - Backoff sequence 2, 4, 8, 16 s; `Retry-After` of 30 s and an HTTP date honoured, capped at 60 s; exactly 5 attempts then `ArchiveError`; 404 returned after 1 attempt; single `User-Agent` header with default and env override
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 6.2, 6.3, 6.4, 6.5_

- [ ] 4. Implement CDX discovery (`cdx.py`)
  - [ ] 4.1 Write query building, page parsing and merging
    - `mimetype_regex(mimetypes)` (regex-escaped members, `text/csv` or `(text/csv|text/xml)`), `build_params(host, path, kind, mimetypes)` for the data pass with `limit=1000`, `showResumeKey=true`, `collapse=digest`, the `fl` list, `filter=statuscode:2..` and one mimetype filter
    - `parse_page(payload)`: map rows by header name, return the one-string row after `[]` as the Resume_Key, raise `CdxParseError` on malformed pages
    - `merge_rows(rows)`: one row per digest, earliest timestamp, sorted by (timestamp, digest)
    - _Requirements: 3.1, 3.2, 3.4_
  - [ ] 4.2 Write `fetch_listing` with resumeKey pagination
    - Loop over Tombstone paths in order and over pages via `resumeKey` until a page has no key; merge into one `Listing` with `ethics_dropped=0` (the filter is added in task 7); raise a discovery error on `ArchiveError`, non-2xx CDX status or `CdxParseError`, so no partial Listing is produced
    - Save the F1, F2 and F3 response excerpts from `requirements.md` Appendix A as fixtures in `tests/exhume/fixtures/` (`cdx_f1.json`, `cdx_f2.json`, `cdx_f3.json`)
    - _Requirements: 3.3, 3.4, 3.5_
  - [ ] 4.3 Write property test P1 in `tests/exhume/test_cdx.py`
    - **Property 1: CDX page parse**: for any permutation of the six header fields, any generated rows and an optional `[]` plus one-string key tail, `parse_page` maps every row by field name, returns the key only when the tail is present and never returns the key as a row; F1 to F3 fixtures parse as expected
    - **Validates: Requirements 3.2**
  - [ ] 4.4 Write example tests for discovery in `tests/exhume/test_cdx.py`
    - Exact query parameters of Req 3.1; MockTransport pagination F1 → F2 → F3 stops at the page without a key and sends `resumeKey`; dedup keeps the earliest timestamp per digest; a parse failure or exhausted retries yields a discovery error
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 3.1, 3.3, 3.4, 3.5_

- [ ] 5. Build the thin vertical slice: store, naive run and CLI wiring, verified live
  - [ ] 5.1 Write the minimal Evidence_Store (`store.py`) and digest helper
    - `atomic_write(path, data)` (temp file in the target dir, `os.replace`, temp removed on failure), `extension(mimetype, kind)`, `entry_key(host, ts, digest)`, `dump_index(index)` (sorted keys, indent 2, trailing newline)
    - `EvidenceStore(root, slug)`: `load_index`, `save_listing` (compact JSON to `cdx/<host>.json`), `save_capture(...)` writing `<host>/<timestamp>-<digest>.<ext>` byte for byte then rewriting `index.json`
    - Create `content.py` with `wayback_digest(body)` only (unpadded upper-case base32 SHA-1); the rest of `content.py` comes in task 6
    - _Requirements: 3.4, 5.3, 7.6, 9.1, 9.2, 9.3_
  - [ ] 5.2 Write the naive orchestration (`run.py`)
    - `wayback_url(timestamp, original)` with `original` unchanged (keeps `:80`, raw `^`); `served_timestamp(response)` from the final URL's `/web/<14 digits>`, else `Memento-Datetime` in UTC, else None
    - `exhume(tombstone, store, archive, max_captures, refresh)`: per Host, `fetch_listing` + `save_listing`, take the first N merged rows (naive pick, replaced in task 8), fetch each through `ArchiveClient`, reject non-429 4xx without retry, store accepted bodies with `digest_verified`; record discovery failures per Host and pass and continue with the next Host; return `RunResult`
    - _Requirements: 3.5, 5.1, 5.2, 5.3, 5.4, 7.6_
  - [ ] 5.3 Wire the CLI `exhume` command (`revenant/cli.py`)
    - Load the Tombstone; on `TombstoneError` print the file and fields and exit 1 before creating any client
    - Build `SystemClock`, `RateLimiter`, `make_client`, `ArchiveClient`, `EvidenceStore(evidence_dir, slug)`; call `exhume`; print plain per-Host counts (the Rich table comes in task 11); exit 1 when any discovery failed
    - `--max-captures` uses `typer.Option(min=1)`, default 50; `--evidence-dir` defaults to `evidence`
    - _Requirements: 2.5, 10.1, 10.4_
  - [ ] 5.4 Write an end-to-end example test in `tests/exhume/test_run.py`
    - MockTransport serving an F1-style CDX page and F5-style CSV bodies; assert capture files at the Req 9.1 paths, an `index.json` with all Req 9.2 fields, `served_timestamp` from the F6 redirect and from `Memento-Datetime`, a 404 data capture rejected after one request, and a CLI run with an invalid Tombstone sending no request
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 2.5, 5.1, 5.2, 5.4, 9.1, 9.2, 9.3_
  - [ ] 5.5 Manual live check against the real Archive
    - Run `.venv\Scripts\revenant exhume yahoo-finance-ichart --max-captures 1` from the repo root
    - Confirm at least 1 capture file exists under `evidence/yahoo-finance-ichart/ichart.yahoo.com/` and `evidence/yahoo-finance-ichart/index.json` lists it with `digest_verified: true`; fix any failure before continuing
    - _Requirements: 5.1, 9.1, 9.2_

- [ ] 6. Implement content checks (`content.py`) and hook them into the client and run
  - [ ] 6.1 Write `is_html`, `is_offline_page` and `classify`
    - `is_html`: Content-Type media type `text/html`, or a body starting with `<!DOCTYPE` or `<html` (case-insensitive) after an optional UTF-8 BOM and whitespace
    - `is_offline_page`: HTML whose first `<title>` contains `Temporarily Offline`, status ignored
    - `classify(body, content_type, cdx_mimetype)`: `error_page` when the body is non-Offline HTML and the CDX mimetype is not `text/html`, else `data`
    - _Requirements: 7.1, 7.2, 7.4_
  - [ ] 6.2 Hook content checks into `ArchiveClient.get` and `run.py`
    - `ArchiveClient.get` treats an Offline page (any status) as retryable under the 5-attempt limit and never returns it as a success
    - `run.py` classifies each Data capture; stores an Error page with `kind="error_page"` and extension `html` while the Slug has fewer than 10 Error_Evidence items, else discards it; counts it as rejected; Offline bodies are never stored
    - Add `EvidenceStore.error_evidence_count()`
    - _Requirements: 6.2, 7.3, 7.5, 9.1_
  - [ ] 6.3 Write property test P2 in `tests/exhume/test_content.py`
    - **Property 2: Offline detector**: for any generated valid CSV, JSON or XML body with a non-`text/html` Content-Type, `is_offline_page` is false; the F9 Offline page is detected with any generated status code, including 200
    - Fixtures: F5 CSV head, an F9 Offline page, the F10 Yahoo 404 HTML, the F11/F12 header-only CSV (`Date,Open,High,Low,Close,Volume,Adj. Close*`)
    - **Validates: Requirements 7.1, 7.2**
  - [ ] 6.4 Write example tests for classification and digests
    - In `tests/exhume/test_content.py`: F10 HTML under a `text/csv` CDX mimetype is `error_page`; header-only CSV is `data`; the F8 known pair: fetch the full F5 body once (one-off script, committed as `tests/exhume/fixtures/f5_goog_weekly.csv`, 15479 bytes) and assert `wayback_digest` is `M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY`
    - In `tests/exhume/test_run.py`: an Offline page with status 200 is retried and not stored; the 11th Error page is discarded; a digest mismatch is stored with `digest_verified=false`
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 7.3, 7.4, 7.5, 7.6_

- [ ] 7. Implement the ethics filter (`ethics.py`) and apply it to Listings
  - [ ] 7.1 Write `has_auth_param`
    - `AUTH_SUBSTRINGS = ("crumb", "cookie", "token", "key", "session", "email")`; parse the query with `parse_qsl(keep_blank_values=True)` so names without values count, percent-decode names and match case-insensitive substrings on names only
    - _Requirements: 8.2, 8.3_
  - [ ] 7.2 Apply the filter in `fetch_listing` and count drops
    - Drop matching rows before merging is saved, set `Listing.ethics_dropped`, so dropped URLs reach no Listing file, no request and no Index entry; in `run.py` set `found = len(rows) + ethics_dropped` and add `ethics_dropped` to `rejected`
    - _Requirements: 8.1, 8.4, 8.5, 10.3_
  - [ ] 7.3 Write property test P5 in `tests/exhume/test_ethics.py`
    - **Property 5: Auth filter matches names only**: for any generated URL, `has_auth_param` is true iff some decoded parameter name contains an Auth substring in any case; Auth substrings placed only in values, the path or the fragment never count; examples `apiKey=x`, `X-Crumb=1`, `%63rumb=1`, `keyword=x` rejected and `s=TOKEN` accepted
    - **Validates: Requirements 8.2, 8.3**
  - [ ] 7.4 Write an example test for drop handling in `tests/exhume/test_run.py`
    - A CDX page with a `crumb=` URL: no request is sent for it, its URL appears in no file under the Evidence_Root, the Listing records `ethics_dropped=1`, and `found`/`rejected` include it
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 8.1, 8.4, 8.5, 10.3_

- [ ] 8. Implement deterministic selection (`select.py`) and replace the naive pick
  - [ ] 8.1 Write query parsing, Parameter shape and Interval
    - `parse_query(original)` with `urlsplit` + `parse_qsl(keep_blank_values=True)` (handles `:80`, any order, `s=^DJI` equals `s=%5EDJI`); `parameter_shape(pairs)` returning `s_only`, `empty_range`, `full_range` or `other`; `interval(pairs)` returning `g` or `none`
    - _Requirements: 4.1_
  - [ ] 8.2 Write `select` and `backfill_order`
    - Dedup by digest (earliest wins), group by (Interval, Parameter shape), sort groups and members by (timestamp, digest), allocate picks round-robin while `k_g < m_g`, take indices `floor(i*m/k)`, output in (group, timestamp, digest) order; no RNG
    - `backfill_order`: unselected Candidates round-robin over sorted groups, each in (timestamp, digest) order
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6_
  - [ ] 8.3 Replace the naive first-N pick in `run.py` with `select`
    - _Requirements: 4.4_
  - [ ] 8.4 Write property test P3 in `tests/exhume/test_select.py`
    - **Property 3: Selection determinism**: for any generated Candidate set (seeded from F1 `original` URLs with varied `g` values, shapes, timestamps and digests), any permutation of it and any N ≥ 1, `select` returns the same rows, at most N, with unique digests
    - **Validates: Requirements 4.3, 4.4, 4.5**
  - [ ] 8.5 Write example tests for selection in `tests/exhume/test_select.py`
    - `parse_query` on F1 URLs and `%5E` symbols; shape classification of each kind; every Group gets one pick when N ≥ number of Groups; `floor(i*m/k)` indices on a known Group; backfill order on a known set
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_

- [ ] 9. Add backfill, Listing cache reuse and idempotent reruns
  - [ ] 9.1 Write the backfill loop in `run.py`
    - After a rejection, exhausted retries or an Error page, fetch the next Candidate in `backfill_order` until N `data` captures are stored for the Host or no Candidate remains
    - _Requirements: 5.5_
  - [ ] 9.2 Write Listing cache reuse, `--refresh` and cached-capture detection
    - `EvidenceStore.load_listing(host, kind)` and `is_cached(host, row)` (Index entry exists and file has the recorded size); `cdx.get_listing(...)` reuses a stored Listing unless `refresh`, else fetches and saves
    - In `run.py`, skip requests for Cached captures and count them as `cached`; apply the rerun short-cut (≥ N cached `data` entries among a Host's Candidates counts N cached, no requests); rewrite `index.json` only when an entry is added so reruns leave it byte-identical
    - _Requirements: 3.4, 9.3, 9.4, 9.5, 9.6_
  - [ ] 9.3 Write example tests in `tests/exhume/test_run.py`
    - 4xx and Offline-exhausted captures are backfilled to N; two runs against the same MockTransport: the second sends no CDX and no capture request, reports 0 downloads and leaves `index.json` byte-identical; `--refresh` sends CDX requests again
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 5.5, 9.4, 9.5, 9.6_

- [ ] 10. Implement the error pass
  - [ ] 10.1 Extend `cdx.py` for the error pass
    - `build_params(..., kind="error")` with `filter=statuscode:4..` and no mimetype filter; `get_listing` caches to `cdx/<host>.errors.json`; Ethics_Filter applies to this pass too
    - _Requirements: 3.6, 3.4, 8.1_
  - [ ] 10.2 Write the error pass in `run.py`
    - After all data downloads, while the Slug has fewer than 10 Error_Evidence items, fetch Error captures round-robin over Hosts in Tombstone order, each Host in (timestamp, digest) order; accept only when the replay status equals the CDX status and `Memento-Datetime` is present, store with `kind="error"`; reject mismatches without retry; skip Cached captures; record error-pass discovery failures per Host
    - _Requirements: 3.5, 3.6, 7.5, 9.4_
  - [ ] 10.3 Write example tests in `tests/exhume/test_run.py`
    - F4-style error Listing and F10 replays: entries stored with `kind="error"`; a 404 without `Memento-Datetime` and a status mismatch are rejected after one request; Error pages from the data pass and Error captures share the cap of 10; round-robin order across two Hosts
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 3.6, 7.5_

- [ ] 11. Implement the Run_Summary and exit codes in the CLI
  - [ ] 11.1 Print the Rich summary in `revenant/cli.py`
    - Rich table with one row per Host in Tombstone order and columns `found`, `downloaded`, `cached`, `rejected`; then a line with the Slug's Error_Evidence count; then each failed Host and pass; exit 1 if any discovery failed, else 0
    - _Requirements: 10.2, 10.3, 10.4_
  - [ ] 11.2 Write CLI example tests in `tests/exhume/test_cli.py`
    - `CliRunner` with a monkeypatched transport and `tmp_path`: `--help` lists all options; summary shows each Host and the four columns and the Error_Evidence line; a CDX failure names the Host and pass and exits 1; `--max-captures 0` is rejected by Typer
    - Checkpoint: run pytest; all non-live tests pass
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [ ] 12. Write the live smoke test (final)
  - [ ] 12.1 Write `tests/exhume/test_live.py` with one `@pytest.mark.live` test
    - Run `revenant exhume yahoo-finance-ichart --max-captures 20` against the real Archive with a `tmp_path` Evidence_Root and the repo's `tombstones/`; assert exit 0, 20 `data` entries for `ichart.yahoo.com` in `index.json`, at least 2 distinct `g` values and at least 3 distinct capture years
    - Run the same command again with the same Evidence_Root; assert exit 0 and `downloaded` is 0 for every Host
    - Run `.venv\Scripts\python -m pytest -m live` once, then `.venv\Scripts\python -m pytest` and `ruff check .`; all pass
    - _Requirements: 10.5, 10.6_

## Notes

- Property tests P1 to P5 are required sub-tasks placed next to their components (tasks 3, 4, 6, 7, 8); none are marked optional.
- Task 5.5 is a manual live check required by the user to confirm the vertical slice before adding features; task 12 automates the full live check.
- The full F5 body fixture (task 6.4) is fetched once with a one-off command and committed; non-live tests never call the Archive.
- Each task references requirement clauses for traceability; checkpoints sit at the end of each task's last sub-task.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "3.1"] },
    { "id": 3, "tasks": ["2.2", "3.2", "4.1"] },
    { "id": 4, "tasks": ["3.3", "4.2"] },
    { "id": 5, "tasks": ["3.4", "4.3"] },
    { "id": 6, "tasks": ["4.4", "5.1"] },
    { "id": 7, "tasks": ["5.2"] },
    { "id": 8, "tasks": ["5.3"] },
    { "id": 9, "tasks": ["5.4"] },
    { "id": 10, "tasks": ["5.5"] },
    { "id": 11, "tasks": ["6.1", "7.1", "8.1"] },
    { "id": 12, "tasks": ["6.2", "7.3", "8.2"] },
    { "id": 13, "tasks": ["6.3", "7.2", "8.4"] },
    { "id": 14, "tasks": ["6.4", "8.3"] },
    { "id": 15, "tasks": ["7.4", "8.5"] },
    { "id": 16, "tasks": ["9.1"] },
    { "id": 17, "tasks": ["9.2"] },
    { "id": 18, "tasks": ["9.3", "10.1"] },
    { "id": 19, "tasks": ["10.2"] },
    { "id": 20, "tasks": ["10.3", "11.1"] },
    { "id": 21, "tasks": ["11.2"] },
    { "id": 22, "tasks": ["12.1"] }
  ]
}
```
