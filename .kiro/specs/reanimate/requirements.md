# Requirements Document

## Introduction

Reanimate is stage 3 of Revenant. `revenant reanimate <slug>` turns the generated Autopsy spec
(`.kiro/specs/revenant-<slug>/requirements.md`, rendered from `crypt/<slug>/contract.json`) into a
running revenant at `crypt/<slug>/server.py`. Kiro CLI headless mode writes the server inside a
temporary Build_Workspace; Kiro IDE chat is the fallback. The server answers `GET /table.csv` as the
dead API did, serving rows from Yahoo's own archived full-history captures (Exhume Appendix A, F18).

The MVP target is `yahoo-finance-ichart`. Success means that this request:

`curl -i "http://127.0.0.1:8000/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv"`

returns status 200, `Content-Type: text/csv`, the Header_Line `Date,Open,High,Low,Close,Volume,Adj Close`,
Data_Rows from 2016-01-08 down to 2016-01-04 that equal Yahoo's archived lines byte for byte, and an
`X-Revenant-Donor` header.

References of the form "Gen x.y" cite acceptance criteria of the generated spec
`.kiro/specs/revenant-yahoo-finance-ichart/requirements.md`. References of the form "F<n>" cite
Exhume Appendix A (`.kiro/specs/exhume/requirements.md`).

## Glossary

- **Runner**: the `revenant reanimate <slug>` command in `revenant/reanimate/`.
- **Tombstone**: the manifest `tombstones/<slug>.toml`.
- **Tombstone loader**: Exhume's `Tombstone` model and `load_tombstone` in `revenant/exhume/models.py`.
- **Contract**: `crypt/<slug>/contract.json`.
- **Generated_Spec**: `.kiro/specs/revenant-<slug>/requirements.md`.
- **CDX_Listing**: Exhume's cached data-pass listing `evidence/<slug>/cdx/<host>.json`. The `cdx/` folder is gitignored, so it exists only on a machine that has run Exhume.
- **Donor_Symbol**: a symbol listed in the Tombstone field `donor_symbols`.
- **Required_Donor_Symbol**: a Donor_Symbol that is also listed in the Tombstone field `donor_required`. Any other Donor_Symbol is optional.
- **Donor_Cover**: the optional Tombstone field `donor_cover`, exactly two ISO dates `[start, end]` with start no later than end, that every Donor_Capture must cover.
- **Full_History**: a candidate query that holds `s`, optionally `g` (absent, empty or `d`) and `ignore`, and no other parameter except any of `a`, `b`, `c`, `d`, `e`, `f` with an empty value; so `s_only`, `empty_range` and `s=AAPL&g=d&ignore=.csv` are all Full_History queries.
- **Donor_Fetcher**: the Runner component that selects, fetches and stores Donor_Captures.
- **Donor_Capture**: the archived body chosen as the row source for one Donor_Symbol, stored as `crypt/<slug>/donor/<file>.csv`.
- **Donor_Index**: `crypt/<slug>/donor/index.json`, one entry per stored Donor_Capture.
- **Served_Timestamp**: the capture timestamp the Archive actually served (F6, F7).
- **Reanimate_Prompt**: `crypt/<slug>/reanimate-prompt.md`, the instruction given to Kiro.
- **Build_Workspace**: a fresh temporary directory, outside the repository, that the Runner creates for one kiro-cli run. It holds copies of only these files: `requirements.md` (the Generated_Spec), `contract.json` (the Contract), `donor/index.json` and `donor/<file>.csv` (the Donor_Index and donor files), `error-404.html` (the Error_Page) and `reanimate-prompt.md` (the Reanimate_Prompt).
- **Build_Path**: how the server was written: `kiro-cli-headless` or `kiro-ide-chat`.
- **Build_Record**: `crypt/<slug>/reanimate.json`.
- **Build_Log**: `crypt/<slug>/reanimate.log`, the kiro-cli `stream-json` stdout plus stderr.
- **Revenant_Server**: the FastAPI app in `crypt/<slug>/server.py`.
- **Error_Page**: `crypt/<slug>/error-404.html`, a copy of the archived 404 body named in Gen 7.1.
- **Check**: the Runner's post-build test of a running Revenant_Server. The Checks are the demo Check (Requirement 6.2), the unknown-symbol Check (Requirement 6.3) and the weekly-interval Check (Requirement 6.4).
- **Daily_Request**: a `GET /table.csv` request whose `g` is `d`, empty or absent.
- **Header_Line**, **Data_Row**, **Row_Date**, **Yahoo_Number**: as defined in the Generated_Spec glossary.
- **Email_Like_String**: a substring matching the regular expression `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}`.
- **Home_Path**: the current user's home directory as returned by `Path.home()`, in its native spelling, its forward-slash spelling and its JSON-escaped spelling (each backslash doubled).
- **Write_Scope**: the directory `crypt/<slug>/`.

## Verified CLI facts

From `kiro-cli chat --help`, kiro-cli 3.5.0, supplied by the user:

- `kiro-cli --version` prints the version, for example `kiro-cli 3.5.0`.
- The prompt is the positional `[INPUT]`. `--output-format stream-json` writes JSON Lines of ACP events to stdout. `--trust-workspace` (V3 only) skips the workspace-trust prompt for one launch.
- Without `--v3`, `--no-interactive` runs the V2 engine, so `--v3` is mandatory.
- With `--no-interactive` on V3, `--trust-tools` accepts V2 tool names. Trusting `fs_write` trusts every tool in its permission capability, file deletion included, and a trusted tool runs on any path. Trust lists therefore cannot fence writes; the Build_Workspace (Requirement 3.2) and the hash check (Requirement 7.1) do.

## Requirements

### Requirement 1: CLI entry and outputs

**User Story:** As the Revenant operator, I want one command that turns a generated spec into a checked revenant, so that the resurrection runs end to end without manual steps.

#### Acceptance Criteria

1. WHEN the operator runs `revenant reanimate <slug>` and every prerequisite check in criterion 2 passes, THE Runner SHALL run the Donor_Fetcher, then the build, then the Check, and SHALL start each stage only after the previous stage has succeeded.
2. IF the Tombstone, the Contract, the Generated_Spec or the archived 404 capture named in Gen 7.1 is missing or fails validation, THEN THE Runner SHALL print the path of each missing or invalid file and exit with code 2, before it makes any network request and before it starts the Donor_Fetcher.
3. WHEN the Runner prepares the build, THE Runner SHALL copy the body of the archived 404 capture named in Gen 7.1 from `evidence/<slug>/` to the Error_Page byte for byte, and after the run every file under `evidence/` SHALL have the same content as before the run, except a CDX_Listing that Exhume's `get_listing` adds or re-saves under Requirement 2.2.
4. WHEN the Donor_Fetcher, the build and the Check all succeed, THE Runner SHALL print a summary listing the stored Donor_Symbols, the missing Donor_Symbols, the Build_Path and the pass or fail result of each Check, and SHALL exit with code 0.
5. THE Runner SHALL create or modify files in the repository only inside the Write_Scope, and only these entries: `server.py`, `donor/`, `error-404.html`, `reanimate-prompt.md`, `reanimate.json` and `reanimate.log`, apart from the CDX_Listing writes of Requirement 2.2 and the temporary Build_Workspace of Requirement 3.2.
6. IF the Donor_Fetcher, the build or the Check fails, THEN THE Runner SHALL print the name of the failed stage, start no later stage, and exit with code 1.

### Requirement 2: Donor selection and storage

**User Story:** As the Revenant operator, I want the revenant to serve Yahoo's own archived rows, so that the data matches what the dead API returned.

#### Acceptance Criteria

1. THE Tombstone loader in `revenant/exhume/models.py` SHALL accept the optional list fields `donor_symbols` and `donor_required`, treat each one as an empty list when it is absent, and reject a Tombstone whose `donor_required` names a symbol missing from `donor_symbols` with an error that names that symbol, accept the optional field `donor_cover` (the Donor_Cover) and reject it unless it holds exactly two `YYYY-MM-DD` dates that parse with start no later than end, so that `tombstones/yahoo-finance-ichart.toml` can list `donor_symbols = ["AAPL", "MSFT", "^GSPC", "YHOO"]` and `donor_required = ["AAPL"]` and `donor_cover = ["2016-01-04", "2016-01-08"]` while Exhume still loads it with its existing fields unchanged.
2. WHEN the Donor_Fetcher selects candidates for a Donor_Symbol that has no Donor_Index entry, or whose entry's file is missing or fails the SHA-256 check, THE Donor_Fetcher SHALL obtain the CDX_Listing of every Tombstone host through Exhume's `get_listing` with kind `data` and `refresh=False` (which reads the cached CDX_Listing and, only when it is missing, fetches it live and writes it to `evidence/<slug>/cdx/`), write nothing else under `evidence/`; decode `&amp` and `&amp;` artifacts in `original` to `&` before parsing the query (F15); keep only rows with status 2xx, a mimetype listed in the Tombstone, a timestamp earlier than `20170501`, an `s` that after percent-decoding exactly equals the symbol (so `%5EGSPC` and `^GSPC` both match `^GSPC`), no auth-like parameter (crumb, cookie, token, key, session, email), and a query that is either Full_History or a `g=d` full range with a non-empty `c` of at most 1999 and either no `f` or an `f` at least equal to the capture's year (F20); drop rows whose digest repeats one already kept; and order the remaining rows by timestamp newest first, breaking ties by `original` in ascending lexical order.
3. WHEN the Donor_Fetcher fetches a candidate, THE Donor_Fetcher SHALL fetch it through Exhume's ArchiveClient (at least 1 second between requests, exponential backoff, User-Agent `Revenant/0.1 (+https://github.com/Manthan-1610/revenant)`, Temporarily Offline detection, Served_Timestamp recorded); accept the candidate as the Donor_Capture only if the Served_Timestamp is earlier than `20170501`, the body's first line is exactly the Header_Line `Date,Open,High,Low,Close,Volume,Adj Close`, the body has at least 1 Data_Row, every Data_Row's Row_Date parses (a single unparseable Row_Date rejects the body; Autopsy found none in 147 bodies), the newest Row_Date is no later than the Served_Timestamp date and at most 7 days before it (contract default `recent_within_7d`), and, when the Tombstone sets a Donor_Cover, the oldest Row_Date is no later than its start and the newest Row_Date is no earlier than its end; try at most 5 candidates per Donor_Symbol in the order of criterion 2; and count a candidate whose fetch fails after the ArchiveClient's retries as one tried candidate that does not qualify.
4. WHEN a Donor_Capture is accepted, THE Donor_Fetcher SHALL store the body bytes unchanged, byte for byte, under `crypt/<slug>/donor/`; name the file with a deterministic form of the symbol that uses only letters, digits, `.`, `-`, `_` and `%` and gives distinct names to distinct symbols (inferred, not backed by archived evidence); and write one Donor_Index entry for the symbol, replacing any earlier entry for it, with the symbol, file name, the `id_` source URL fetched, host, Served_Timestamp, SHA-256 of the stored bytes, Data_Row count, and the oldest Row_Date as first date and the newest Row_Date as last date, both `YYYY-MM-DD`.
5. WHEN the Donor_Fetcher processes a Donor_Symbol whose Donor_Index entry exists and whose stored file's SHA-256 matches that entry, THE Donor_Fetcher SHALL reuse the stored file and entry unchanged and make zero Archive requests for that symbol.
6. IF no candidate qualifies for a Donor_Symbol after at most 5 tries, or the CDX_Listings contain no candidate for the symbol, THEN THE Donor_Fetcher SHALL report the symbol as missing with a message that names the symbol and says that no capture qualified, write no Donor_Index entry or donor file for the symbol, leave existing donor files unchanged, remove the symbol's Donor_Index entry when it existed but its stored file was missing or failed the SHA-256 check (leaving that file's bytes on disk) and say so in the message, continue with the remaining symbols when the symbol is optional, and make the Runner exit with code 1 before the build starts when the symbol is a Required_Donor_Symbol.

### Requirement 3: Reanimate prompt and headless build

**User Story:** As a hackathon entrant, I want Kiro CLI headless mode to write the server from the generated spec, so that the build is reproducible and shows deep Kiro use.

#### Acceptance Criteria

1. WHEN the Donor_Fetcher succeeds, THE Runner SHALL write the Reanimate_Prompt before any kiro-cli invocation, replacing any earlier Reanimate_Prompt, and the Reanimate_Prompt SHALL name its inputs only by their relative file names inside the Build_Workspace (`requirements.md`, `contract.json`, `donor/index.json`, `error-404.html`), name `server.py` in the Build_Workspace as the single file to write, state that no shell or command tool is available so Kiro writes only `server.py` and makes no attempt to run, test or install anything, state the constraints of Requirements 5 and 7.3, and cite after each server rule the Generated_Spec criterion that the rule implements (for example "Gen 3.2").
2. WHILE the Build_Path is `kiro-cli-headless`, WHEN the Reanimate_Prompt has been written, THE Runner SHALL create a fresh Build_Workspace holding copies of only the files listed in the Build_Workspace glossary entry, and run exactly `kiro-cli chat --v3 --no-interactive --trust-workspace --trust-tools=fs_read,fs_write --output-format stream-json "Read reanimate-prompt.md in this directory and follow it exactly."` with the Build_Workspace as the working directory, trusting no shell-execution or web tool.
3. IF `kiro-cli` is not on the PATH, or `kiro-cli whoami` exits with a non-zero code, THEN THE Runner SHALL print a message that names the missing prerequisite and the `--prompt-only` and `--built-by kiro-ide-chat` fallback options of Requirement 4, and exit with code 2 before invoking `kiro-cli chat`.
4. WHEN kiro-cli runs, THE Runner SHALL save the complete `stream-json` stdout and the stderr to the Build_Log with each line labelled by its stream, replacing any earlier Build_Log, and SHALL also write the Build_Log with all output captured so far when kiro-cli exits with a non-zero code or is stopped by the 15-minute limit.
5. IF kiro-cli exits with a non-zero code (including code 1 for a prompt that does not fit the context window, CLI 3.4.0 and later), is still running 15 minutes after it was started, or exits with code 0 while the Build_Workspace holds no `server.py`, THEN THE Runner SHALL terminate the kiro-cli process if it is still running, record in the Build_Record the exit code, a null exit code marked as a timeout, or the note that kiro-cli wrote no server, keep the Build_Workspace and print its path with the Home_Path replaced by `~`, skip the Check, print no success message, and exit with code 1.
6. WHEN kiro-cli exits with code 0 and the Build_Workspace holds `server.py`, THE Runner SHALL copy that file byte for byte to `crypt/<slug>/server.py`, replacing any earlier server, and then delete the Build_Workspace.

### Requirement 4: IDE fallback and build provenance

**User Story:** As the Revenant operator, I want a recorded fallback through Kiro IDE chat, so that the revenant can still be built when headless mode is unavailable.

#### Acceptance Criteria

1. WHERE the `--prompt-only` option is given, THE Runner SHALL run the Donor_Fetcher, write the Reanimate_Prompt, print its path, and exit with code 0 without invoking kiro-cli, without requiring `kiro-cli` on the PATH or a kiro-cli login, and without running the Check, so that the operator can paste that same Reanimate_Prompt into Kiro IDE chat.
2. WHERE the `--built-by kiro-ide-chat` option is given, THE Runner SHALL run the Donor_Fetcher, replace the build stage of Requirement 1.1 with no kiro-cli invocation and no check for `kiro-cli` on the PATH or `kiro-cli whoami`, create no Build_Workspace, leave the existing Reanimate_Prompt and `crypt/<slug>/server.py` unchanged, and run the Check with Build_Path `kiro-ide-chat`.
3. IF the `--built-by kiro-ide-chat` option is given and `crypt/<slug>/server.py` or the Reanimate_Prompt does not exist, THEN THE Runner SHALL name each missing file, run no Check, write no Build_Record, and exit with code 2.
4. WHEN a `kiro-cli-headless` build finishes (with exit code 0, a non-zero exit code, or the 15-minute stop of Requirement 3.5) or a `--built-by kiro-ide-chat` run finishes, THE Runner SHALL write the Build_Record with the Build_Path, the SHA-256 of the Reanimate_Prompt bytes on disk as given to Kiro (after the redaction of Requirement 7.2), the kiro-cli version and kiro-cli exit code (both null for `kiro-ide-chat`), the `model` id as reported by a `stream-json` event of the run (null when no event reports a model id, and for `kiro-ide-chat`), start and end times in ISO 8601 UTC, the Write_Scope result of Requirement 7.1, and each Check result (null for each Check that did not run).
5. WHEN the Build_Path is `kiro-cli-headless` and the Runner has passed the checks of Requirement 3.3, THE Runner SHALL run `kiro-cli --version` before invoking `kiro-cli chat`, and store that command's stdout, with leading and trailing whitespace removed (for example `kiro-cli 3.5.0`), as the kiro-cli version in the Build_Record.
6. IF `kiro-cli --version` exits with a non-zero code, prints empty stdout, or runs longer than 30 seconds, THEN THE Runner SHALL name the IDE fallback of criterion 2 and exit with code 2 without invoking `kiro-cli chat`.

### Requirement 5: Revenant server behaviour

**User Story:** As an unmodified old client, I want `GET /table.csv` to answer as the dead API did, so that my code works again without changes.

#### Acceptance Criteria

1. WHEN the Revenant_Server receives a Daily_Request for which the Donor_Capture of `s` has at least one Data_Row whose Row_Date falls between the resolved start date and the resolved end date (both inclusive), THE Revenant_Server SHALL respond with status 200, `Content-Type: text/csv`, the Donor_Capture's Header_Line `Date,Open,High,Low,Close,Volume,Adj Close` as the first line, and then every such Data_Row and no other row, each copied byte for byte from its Donor_Capture line with no reformatting of any Yahoo_Number (zero Volume stays `000`), in the Donor_Capture's newest-first order (Gen 1.1–1.3, 4.1, 4.2, 4.4, 4.7; F23, F24).
2. WHEN the Revenant_Server parses a request, THE Revenant_Server SHALL route the path `/table.csv` whatever the Host header value and apply Gen 2.1–2.6, 2.8–2.14, 3.1 and 3.2: read `a` and `d` as 0-indexed months (`a=0` is January), accept out-of-range integers without rejecting the request, roll a month value of 12 over to January of the following year, then clamp a day beyond that month's length to the month's last day (inferred, not backed by archived evidence), and treat `s=^GSPC` and `s=%5EGSPC` as the same symbol with identical responses.
3. WHEN a Daily_Request is `s_only` or `empty_range`, or any one of `a`, `b`, `c` is absent, empty or not an integer (for example the F17 template value `c={{(-1 month).year}}`), THE Revenant_Server SHALL treat the whole start date as missing and use the earliest Row_Date in the Donor_Capture, treat `d`, `e`, `f` the same way for the end date using the latest Row_Date in the Donor_Capture (Gen 5.1, 5.2), and respond as in criterion 1 with status 200 and no unhandled exception.
4. IF a Daily_Request has `s` absent or empty, has an `s` with no Donor_Capture, or has a resolved range (including a start date after the end date) that holds no Data_Row, THEN THE Revenant_Server SHALL respond with status 404, `Content-Type: text/html` and the Error_Page body, with no CSV content (Gen 7.1, F4).
5. IF a request carries a non-empty `g` other than `d` (including `w`, `m` and `v`), THEN THE Revenant_Server SHALL respond with status 404, `Content-Type: text/html`, the Error_Page body and an `X-Revenant-Note` header stating that the interval is not reanimated yet, applying this check before the `s` and range checks of criterion 4.
6. WHEN the Revenant_Server sends any response, including a 404 response, THE Revenant_Server SHALL include exactly one `X-Revenant-Donor` header whose value is `wayback:<host>/<Served_Timestamp>` when `s` has a Donor_Capture, where `<host>` is the hostname of that Donor_Capture's original URL (not the request's Host header) and `<Served_Timestamp>` is the timestamp the Archive actually served, and whose value is `none` when `s` is absent, empty or has no Donor_Capture (Gen 6.1).

### Requirement 6: Post-build Check

**User Story:** As the Revenant operator, I want the Runner to prove the built server works before it claims success, so that a broken build is never reported as alive.

#### Acceptance Criteria

1. WHEN the build step completes without error, THE Runner SHALL start the Revenant_Server with uvicorn bound to 127.0.0.1 on a port that no other process is listening on at start time, and treat the Revenant_Server as answering once it returns any HTTP response, waiting at most 30 seconds from process start.
2. WHEN the Revenant_Server answers, THE Check SHALL send the demo request `/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv` and pass only if a response arrives within 10 seconds with status 200, a `Content-Type` media type of `text/csv` (ignoring parameters such as charset), a first line exactly equal to the Header_Line `Date,Open,High,Low,Close,Volume,Adj Close`, exactly five Data_Rows whose Row_Dates are 2016-01-08, 2016-01-07, 2016-01-06, 2016-01-05 and 2016-01-04 in that order and each of which equals the AAPL Donor_Capture's line for that Row_Date byte for byte, and an `X-Revenant-Donor` value equal to the one derived from the AAPL Donor_Index entry.
3. WHEN the demo Check passes, THE Check SHALL send the demo request with the `s` value replaced by a symbol that has no Donor_Capture, and pass only if a response arrives within 10 seconds with status 404 and a `Content-Type` media type of `text/html`.
4. WHEN the demo Check passes, THE Check SHALL send the demo request with `g=d` replaced by `g=w`, and pass only if a response arrives within 10 seconds with status 404 and a non-empty `X-Revenant-Note` header.
5. WHEN the Check sequence ends (every Check whose precondition held has run, the demo Check has failed, or the 30-second wait has expired), THE Runner SHALL stop the Revenant_Server process, confirm that the process has exited within 10 seconds, and force-terminate the process if it has not exited.
6. IF the Revenant_Server does not answer within 30 seconds, the Revenant_Server process exits before answering, or any Check fails (including no response within 10 seconds), THEN THE Runner SHALL print each failed Check with its expected and observed value, record a pass, fail or not-run result for every Check in the Build_Record, print no success message, and exit with code 1.

### Requirement 7: Safety, scope and committed artifacts

**User Story:** As a contributor bound by necromancy ethics and the hackathon rules, I want the build confined, secret-free and reproducible, so that a trusted headless agent cannot damage the repository and the demo runs without kiro-cli.

#### Acceptance Criteria

1. IF a comparison of the path and SHA-256 of every repository file (excluding the Build_Log, the directories `.git/`, `.venv/`, `.hypothesis/`, `.pytest_cache/` and `.ruff_cache/` at the repository root, and every `__pycache__/` directory at any depth), taken immediately before kiro-cli starts and immediately after kiro-cli exits or is stopped and before the copy of Requirement 3.6, shows any file created, changed or deleted, inside or outside the Write_Scope, THEN THE Runner SHALL list each such path with its change type (created, changed or deleted), record the list in the Build_Record, leave the files as they are, skip the Check, print no success message, and exit with code 1, because kiro-cli runs in the Build_Workspace and a trusted `fs_write` may delete or write on any path.
2. THE Runner SHALL, before writing the Reanimate_Prompt, the Build_Log, the Build_Record or any console output, replace the `KIRO_API_KEY` value (when set and non-empty) and every Email_Like_String with `[REDACTED]` and every Home_Path occurrence with `~`, and SHALL discard the stdout of `kiro-cli whoami` without writing it to any file or console output, so that after a run whose stubbed kiro-cli prints a fake key, a fake email address and a fake home path, no file in the Write_Scope and no console output contains any of the three.
3. THE Revenant_Server SHALL import only `fastapi`, `uvicorn` and modules of the Python standard library, resolve the Donor_Index, the Donor_Captures and the Error_Page from the directory that contains `server.py` so that it gives identical responses whatever directory it is started from, and at runtime make no outbound network request and read no file under `evidence/`.
4. IF `server.py` imports any module other than `fastapi`, `uvicorn` or a Python standard library module, or references a path under `evidence/`, THEN THE Runner SHALL name the offending import or path, record it in the Build_Record, skip the Check, print no success message, and exit with code 1.
5. WHEN a run that wrote the Write_Scope outputs finishes, THE Runner SHALL have written `server.py`, `donor/`, `error-404.html`, `reanimate-prompt.md`, `reanimate.json` and `reanimate.log` only to paths that no `.gitignore` rule matches, and the repository `.gitattributes` SHALL mark `crypt/*/donor/**` and `crypt/*/error-404.html` as `-text`, so that these files are committed, the committed donor and Error_Page bytes reach every clone unchanged (so the SHA-256 reuse check of Requirement 2.5 triggers no live refetch), and the deployed demo runs without kiro-cli.
6. THE Reanimate unit test suite SHALL pass with no network connection, no `KIRO_API_KEY` and no kiro-cli login, using `httpx.MockTransport` with fixtures from `evidence/` and a stubbed kiro-cli process (including `whoami` and `--version`) in place of the real one, and every test that makes a live Archive request or a live kiro-cli run SHALL carry `@pytest.mark.live` so that the default `-m 'not live'` run skips it.

## Deferred

- Aggregated intervals `g=w` and `g=m`, and dividends `g=v` (Gen 2.7, 4.3, 4.5, 4.6). The MVP answers them with 404 and `X-Revenant-Note` (Requirement 5.5).
- An Alpha Vantage donor for dates after the Donor_Capture's last Row_Date.
- HTTPS serving or interception.
- Runs over several slugs in one command.

## Resolved decisions

- Tombstone gains optional `donor_symbols` and `donor_required` (2.1); Exhume's `extra="forbid"` model must add them.
- Donor candidates: no `f` or `f` ≥ capture year, newest Row_Date within 7 days of the Served_Timestamp, at most 5 tries (2.2, 2.3).
- Full_History queries replace `s_only` as the first candidate branch, and the Donor_Cover `["2016-01-04", "2016-01-08"]` makes the demo rows a donor requirement (2.2, 2.3). Reason: the live AAPL run found no qualifying capture, while capture 20161222215700 (`ichart.finance.yahoo.com/table.csv?s=AAPL&g=d&ignore=.csv`, 9,086 rows 1980-12-12..2016-12-21, digest MDRWYAZNZBP2FGOSFRQZUCHKYS4F2YVU) holds all five demo rows.
- A body with any unparseable Row_Date is rejected (2.3). A stored donor that fails its SHA-256 check and has no qualifying replacement loses its Donor_Index entry; its file stays on disk (2.6).
- Rejected: measuring freshness against the requested end date instead of the Served_Timestamp, and relaxing the `f` rule.
- Rows are copied byte for byte with no reformatting (5.1, 6.2; F23, F24, landed in commit e9f49b7: Gen 4.2, 4.3, 4.4 and 4.6 use Yahoo_Number with `000` zero Volumes, Gen 4.5 uses 6 fixed decimals). `g=w`, `g=m`, `g=v` answer 404 (5.5).
- `X-Revenant-Donor: none` without a Donor_Capture (5.6). The 404 body is copied to the Error_Page (1.3). Header-only ranges answer 404 (5.4, 6.3).
- A stored kiro-cli login is allowed; `kiro-cli whoami` gates the headless build (3.3).

## Open items

1. The supplied help text covers `kiro-cli chat` and `--version`, not `kiro-cli whoami`. Confirm that `whoami` exits non-zero when no login exists.
