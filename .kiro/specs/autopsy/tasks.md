# Implementation Plan: Autopsy

> **Hold:** do not commit and do not start any task until the user says "Session A is done"
> (another session is committing on `main`).

## Overview

Python 3.12 implementation of `revenant autopsy <slug>`, following the modules in `design.md`
(`revenant/autopsy/{evidence,normalize,body,months,infer,contract,render}.py` and the `autopsy` command in
`revenant/cli.py`). The plan builds a thin vertical slice first: by the end of task 4,
`revenant autopsy yahoo-finance-ichart` on the committed `evidence/yahoo-finance-ichart/` writes
`crypt/yahoo-finance-ichart/contract.json` with the month indexing and prints both Decisive counts.
Tasks 5 to 7 fill in the remaining Contract sections, task 8 adds the renderer, task 9 completes the CLI
tests and task 10 runs everything on the real evidence.

Reused from Exhume, imported and never copied: `Index`, `IndexEntry` (`revenant.exhume.models`),
`parse_query`, `parameter_shape`, `interval` (`revenant.exhume.select`) and `atomic_write`
(`revenant.exhume.store`). Entries with `digest_verified=false` are genuine evidence (F19) and are used
exactly like verified entries; only the SHA-256 check of Req 1.3 gates a body.

Tests use pytest and Hypothesis in `tests/autopsy/`. They build evidence in `tmp_path` from synthetic
bodies; some examples read the committed `evidence/yahoo-finance-ichart/` read-only. No test creates an
httpx client or touches the network. Each property test uses `@settings(max_examples=100)` and the comment
`# Feature: autopsy, Property <n>: <title>`.

**Execution rules (every task):**
- After each task run `.venv\Scripts\ruff check .`, `.venv\Scripts\ruff format .` and
  `.venv\Scripts\python -m pytest`; all must pass.
- Commit with the message `autopsy: task N - <title>` (only after the hold above is lifted).
- Each task report is at most 8 lines.
- If a test fails twice, stop and report instead of trying again.

## Tasks

- [x] 1. Implement the Evidence_Reader (`evidence.py`) and the CLI stub
  - [x] 1.1 Write `AutopsyError`, `Capture`, `load_evidence`, `capture_year` and `capture_date`
    - `AutopsyError(path: str, message: str)`: the single input-error type, `str()` gives `<path>: <message>` with a POSIX path
    - `@dataclass(frozen=True) Capture(key, entry, body)`
    - `load_evidence(evidence_dir, slug) -> tuple[bytes, list[Capture]]`: read `<evidence_dir>/<slug>/index.json` as bytes, validate with Exhume's `Index.model_validate_json`; raise `AutopsyError` for a missing file, bad JSON, validation failure or slug mismatch; read every body from `<evidence_dir>/<slug>/<entry.path>` in sorted key order; raise for a missing body or a SHA-256 mismatch; accept `digest_verified=false` entries unchanged
    - `capture_year(entry)` and `capture_date(entry)` from `served_timestamp`, else `requested_timestamp`
    - Create `tests/autopsy/__init__.py`
    - _Requirements: 1.2, 1.3, 1.4_
  - [x] 1.2 Add the `autopsy` command stub to `revenant/cli.py`
    - `autopsy(slug, evidence_dir=Path("evidence"), crypt_dir=Path("crypt"), specs_dir=Path(".kiro/specs"))`, a sibling of `exhume`; for now it calls `load_evidence`, prints the capture count, and turns `AutopsyError` into `error: <file>: <message>` on stderr and exit 1
    - _Requirements: 1.1, 1.3_
  - [x] 1.3 Write example tests in `tests/autopsy/test_evidence.py`
    - Valid evidence loads in sorted key order regardless of Index insertion order; each Req 1.3 failure (missing Index, bad JSON, invalid Index, slug mismatch, missing body, SHA-256 mismatch) raises `AutopsyError` naming the file; a `digest_verified=false` entry is accepted; `capture_year`/`capture_date` fall back to `requested_timestamp`; the committed evidence loads without error
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 1.2, 1.3, 1.4_

- [x] 2. Implement the Query_Normalizer (`normalize.py`) and the Body_Parser core (`body.py`)
  - [x] 2.1 Write `unescape_fixpoint` and `normalize_query`
    - `unescape_fixpoint(text)`: `html.unescape` until unchanged
    - `normalize_query(original)`: `urlsplit(original).query` → `unescape_fixpoint` → Exhume's `parse_query("?" + query)`; Capture_Shape and Interval come from Exhume's `parameter_shape` and `interval` on these pairs
    - _Requirements: 2.1_
  - [x] 2.2 Write property test P3 in `tests/autopsy/test_normalize.py`
    - **Property 3: Unescape fixpoint**: for any query over `[A-Za-z0-9^%.=&]` HTML-escaped 0 to 3 times, `normalize_query` returns the same pairs as Exhume's `parse_query` on the unescaped query; example `&amp;amp;d=0` yields `d=0` (F15)
    - **Validates: Requirements 2.1**
  - [x] 2.3 Write `ParsedBody`, `parse_body`, `parse_row_date` and `row_order`
    - `parse_body(body, path)`: strict UTF-8 decode (raise `AutopsyError` naming `path`), no newline conversion, split at `\n`, Header_Line, Comment_Lines by `^<!--.*-->\s*$`, Data_Rows (non-empty, non-comment), `comments_after_last_row` and `comments_before_last_row`
    - `parse_row_date(field, capture_year) -> tuple[date, str] | None`: `%Y-%m-%d` or `%d-%b-%y` with a fixed English month table (never the locale); two-digit year `yy` → `capture_year - ((capture_year - yy) % 100)`
    - `row_order(dates)`: `descending`, `ascending` or `unordered`; needs ≥ 2 dates
    - _Requirements: 4.2, 4.3, 5.2, 5.3_
  - [x] 2.4 Write property test P4 in `tests/autopsy/test_body.py`
    - **Property 4: Parsed row order**: for any strictly descending date list of length ≥ 2 within the 100 years up to the Capture_Year, each row rendered in either Row_Date format, `row_order` of the parsed dates is `descending`; month and year boundaries (where string order fails) are included
    - **Validates: Requirements 5.2**
  - [x] 2.5 Write example tests in `tests/autopsy/test_body.py`
    - F16 comment line after the last row; Header_Only_Body (F12); a non-UTF-8 body raises `AutopsyError` naming the file; both date formats including a two-digit year across a century; an unparseable Row_Date returns None
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 4.2, 4.3, 5.3_

- [x] 3. Implement the Month_Detector (`months.py`)
  - [x] 3.1 Write `MonthSample`, `fits`, `MonthResult` and `detect`
    - `fits(sample, h)`: false for any non-integer `a` to `f` or an invalid start `date(c, a + 1 - h, b)` / end `date(f, d + 1 - h, e)`; true when start ≤ oldest ≤ newest ≤ end
    - `detect(samples)`: classify each sample as Decisive (per H), Ambiguous or Unfit; `0-indexed` or `1-indexed` when that offset has ≥ 3 Decisive and the other has none, else `undetermined`; return the four counts with up to 3 sorted keys each; Ambiguous and Unfit get no vote
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - [x] 3.2 Write property test P1 in `tests/autopsy/test_months.py`
    - **Property 1: Month recovery**: for any H in {0, 1} and any sample set generated with H containing ≥ 3 Decisive_Captures plus Ambiguous or Unfit noise, `detect` returns H's indexing; adding one Decisive_Capture for the other offset returns `undetermined`
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
  - [x] 3.3 Write example tests in `tests/autopsy/test_months.py`
    - Non-integer and empty `a` values are Unfit; `b=31` with an invalid month is Unfit for that H; exactly 2 Decisive gives `undetermined`; counts and keys are stored as specified
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 3.1, 3.3, 3.4_

- [x] 4. Build the vertical slice: minimal Contract, inference, writer and CLI, verified on real evidence
  - [x] 4.1 Write the slice models and writer in `contract.py`
    - Models with `ConfigDict(extra="forbid", frozen=True)`: `Evidence`, `Source`, `HostEvidence`, `Endpoint`, `Months`, and `Contract` with `slug`, `source`, `endpoints`, `months` (later tasks add the other fields of the design's Data Models)
    - `dump_contract` (Exhume's `dump_index` recipe: sorted keys, indent 2, `ensure_ascii=False`, trailing `\n`, UTF-8), `write_contract` via `atomic_write` to `<crypt_dir>/<slug>/contract.json`, `load_contract` via `model_validate_json`
    - _Requirements: 7.1, 7.3, 7.4, 7.5_
  - [x] 4.2 Write the slice inference in `infer.py`
    - `infer(slug, index_bytes, captures) -> Contract`: re-sort captures by key; keep `data` for facts, ignore `error_page`; `Source` from the SHA-256 and entry count of `index_bytes`; endpoints per `urlsplit(original).path` with hosts and per-(host, path) Evidence; build `MonthSample`s from `full_range` Data_Captures with ≥ 1 Data_Row and all Row_Dates parsed, and call `detect`
    - One private helper per requirement group; no set or dict iteration without sorting; no time, path, locale or env value enters the Contract
    - _Requirements: 1.4, 2.2, 3.1, 7.3, 7.5_
  - [x] 4.3 Wire the CLI flow in `revenant/cli.py`
    - `load_evidence` → `infer` → `write_contract`; print the month indexing, the Decisive counts for H=0 and H=1 and the written path (POSIX); exit 2 when indexing is `undetermined` (contract written, no spec)
    - _Requirements: 1.5, 3.5, 7.1_
  - [x] 4.4 Write property test P2 in `tests/autopsy/test_contract.py`
    - **Property 2: Byte-identical contract**: for any synthetic evidence set and any permutation of its captures, `dump_contract(infer(...))` returns the same bytes; the generator is extended in tasks 5 to 7 as fields are added
    - **Validates: Requirements 7.4, 7.6**
  - [x] 4.5 Run the slice on the real evidence
    - Write `tests/autopsy/test_infer.py::test_committed_evidence_is_0_indexed` (reads `evidence/yahoo-finance-ichart/` read-only, asserts `0-indexed` and Decisive H=1 is 0)
    - Run `.venv\Scripts\revenant autopsy yahoo-finance-ichart` from the repo root; confirm exit 0, `crypt/yahoo-finance-ichart/contract.json` exists with `months.indexing` and both Decisive counts printed; fix any failure before continuing
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 1.5, 3.2, 7.1_

- [x] 5. Add parameters and content types to the Contract
  - [x] 5.1 Add `Parameter`, `IntType`, `EnumType`, `StringType`, `ValueCount`, `NameEvidence` and the `parameters`, `amp`, `content_types` fields to `contract.py`
    - Type union discriminated by `kind`; `parameters` sorted by name, `examples` by (count desc, value asc), enum `values` by value
    - _Requirements: 2.3, 2.4, 2.5, 4.1, 7.3_
  - [x] 5.2 Infer parameters and content types in `infer.py`
    - Per name except `amp`, using each capture's first value: presence Evidence, empty count, Template_Junk count (`{{`, `}}`, `{%`, or a non-digit `a` to `f` value such as `f=f6j1`), `required` only when every Data_Capture has a non-empty value, up to 5 examples; type `int` (min, max) when all non-empty non-junk values are ASCII digits, else `enum` (≤ 10 distinct), else `string` (distinct count); each `int` parameter records its observed min and max (Req 8.2 renders the full range); `documented` false outside the Documented_Parameters ("observed, unexplained", optional); `amp` Evidence
    - Content types: lowercased part before `;` of `content_type`, else `mimetype`, with Evidence per type
    - _Requirements: 2.3, 2.4, 2.5, 4.1_
  - [x] 5.3 Write example tests in `tests/autopsy/test_infer.py` and extend the P2 generator
    - `a` typed `int`, `g` typed `enum`, `s` typed `string`; `amp` counted and excluded; template junk counted; undocumented `x` optional; `text/csv; charset=...` reduces to `text/csv`; on the committed evidence `d` is `int` with max 12 (F21)
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 2.3, 2.4, 2.5, 4.1_

- [x] 6. Add response variants and row format to the Contract
  - [x] 6.1 Add `body_precision` to `body.py`
    - Maximum fractional digits over numeric fields of Data_Rows, skipping the `Date` and `Volume` columns
    - _Requirements: 5.4_
  - [x] 6.2 Add `Variant`, `IntervalVariants`, `FormatEvidence`, `RowOrder`, `Precision`, `DigitsCount`, `Comments` and the fields `intervals`, `headers`, `header_only`, `date_formats`, `row_order`, `precision`, `comments` to `contract.py`
    - _Requirements: 4.4, 4.5, 4.6, 5.1, 5.2, 5.4, 5.5_
  - [x] 6.3 Infer the sections in `infer.py`
    - Response_Variants per Interval with columns and year range; Header_Variants with year range; Header_Only_Body count (included in variant counts, excluded from Req 3, 5, 6 checks); Row_Date formats with year range; row-order classes plus `unparsed_dates` (excluded from row-order, month and default checks); precision per (Interval, header, year); comment totals, years, first example in key order, after/before last row
    - _Requirements: 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5_
  - [x] 6.4 Write example tests in `tests/autopsy/test_infer.py` and `tests/autopsy/test_body.py`, and extend the P2 generator
    - `g=v` maps to `Date,Dividends`; `Adj. Close*` and `Adj Close` are separate variants with their year ranges (F12); Header_Only_Body counted but not in row order; F16 comment counted after the last row with its example; precision on a known body
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 4.4, 4.5, 4.6, 5.1, 5.2, 5.4, 5.5_

- [x] 7. Add defaults, errors and Contract validation errors
  - [x] 7.1 Add `Default`, `ErrorStatus`, `NameCount` and the `defaults` and `errors` fields to `contract.py`
    - _Requirements: 6.1, 6.4, 6.5_
  - [x] 7.2 Infer defaults and errors in `infer.py`
    - Per shape `s_only` and `empty_range` (≥ 1 Data_Row, no `unparsed_dates`): Evidence, earliest oldest and latest newest Row_Date (0 and null when none), `recent_within_7d` (Capture_Date minus newest Row_Date in 0..7), spacing from `statistics.median` of pooled absolute gaps (`d` ≤ 4, `w` 5..10, `m` 25..35, else `unknown`)
    - Errors per status from Error_Captures only: Evidence, media types, Capture_Shape counts; `None` when no Error_Capture exists
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [x] 7.3 Handle Contract `ValidationError` in the CLI
    - Print `error: contract.json: <loc>: <message>`, keep any existing `contract.json` untouched, exit 1
    - _Requirements: 7.2_
  - [x] 7.4 Write example tests in `tests/autopsy/test_infer.py` and extend the P2 generator
    - Default spacing `d`, `w`, `m` and `unknown` (including a 4.5 median and no gaps); `recent_within_7d` at 7 and 8 days; errors present with counts and `None` without Error_Captures; `error_page` entries ignored
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 1.4_

- [x] 8. Implement the Spec_Renderer (`render.py`) and wire it into the CLI
  - [x] 8.1 Write `render` and `write_spec`
    - Fixed section order, f-strings and `"\n".join`, one trailing newline; EARS requirements for routes (every host alias and path), each parameter with type and required/optional, for each `int` parameter a requirement to accept every value from the observed min to the observed max and never reject a value Yahoo accepted (`d` up to 12, F21), month indexing, the row-order class with the highest count, each shape's default range, the `X-Revenant-Donor` header
    - Served variant per Interval: latest last year, then higher Evidence, then lowest header; served precision: most frequent in the latest year, ties to more digits; error requirement for the top status (ties to lower code) with its top content type (ties to code-point order) when the donor has no rows
    - Informational section: unselected variants, every Row_Date format, the Comment_Line example, and that "observed, unexplained" parameters are ignored
    - `write_spec` via `atomic_write` to `<specs_dir>/revenant-<slug>/requirements.md`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - [x] 8.2 Wire rendering into the CLI flow
    - After `write_contract` and the `undetermined` check: `load_contract` from disk → `render` → `write_spec`; print the spec path
    - _Requirements: 1.5, 8.1_
  - [x] 8.3 Write example tests in `tests/autopsy/test_render.py`
    - Rendering a fixed contract twice gives identical bytes; each tie-break of Req 8.3, 8.4 and 8.6; no error requirement when `errors` is null; the informational section lists unselected variants; the rendered spec states the full observed range (min to max) of each `int` parameter
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 8.1, 8.3, 8.4, 8.5, 8.6_

- [x] 9. Write the CLI tests
  - [x] 9.1 Write `tests/autopsy/test_cli.py` with `CliRunner` and `tmp_path` evidence
    - Exit 0 writes both files and prints the indexing, both Decisive counts and each path; exit 1 for each input error with no file written or modified; a non-UTF-8 body exits 1; `undetermined` exits 2 with `contract.json` only; a Contract `ValidationError` exits 1, prints `error: contract.json: ...` and leaves an existing `contract.json` untouched (monkeypatch to force it); two runs from two working directories (absolute `--evidence-dir` vs relative) give byte-identical `contract.json`; `--help` lists the three options
    - Checkpoint: run ruff and pytest; all non-live tests pass
    - _Requirements: 1.1, 1.3, 1.5, 3.5, 4.3, 7.2, 7.6_

- [x] 10. Final run on the real evidence
  - [x] 10.1 Run `.venv\Scripts\revenant autopsy yahoo-finance-ichart` from the repo root and report
    - Confirm exit 0 and both `crypt/yahoo-finance-ichart/contract.json` and `.kiro/specs/revenant-yahoo-finance-ichart/requirements.md` exist; run it again and confirm both files are byte-identical
    - Show the key facts of the contract: endpoint and hosts, month indexing with the four counts, Header_Variants with year ranges, row-order counts, served variant per `g`, defaults per shape, errors
    - Show the first 40 lines of the rendered `requirements.md`
    - Run ruff check, ruff format and pytest; all pass
    - _Requirements: 1.5, 7.6, 8.1, 8.2_

## Notes

- Hold: no commit and no task starts until the user says "Session A is done".
- Execution rules from the Overview apply to every task: ruff check, ruff format and pytest after each task; commit as `autopsy: task N - <title>`; reports of at most 8 lines; stop and report after a test fails twice.
- Property tests P1 to P4 are required sub-tasks placed next to their components (tasks 2, 3, 4); none are marked optional. P2 starts with the slice Contract and its generator grows with tasks 5 to 7.
- `digest_verified=false` entries (F19) are treated exactly like verified entries.
- No duplication of Exhume code: `Index`, `IndexEntry`, `parse_query`, `parameter_shape`, `interval` and `atomic_write` are imported.
- Unit tests never touch the network; the committed evidence is read-only in tests.
- Each task references requirement clauses for traceability; checkpoints sit at the end of each task's last sub-task.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["2.4", "3.2"] },
    { "id": 4, "tasks": ["2.5", "3.3", "4.1"] },
    { "id": 5, "tasks": ["4.2"] },
    { "id": 6, "tasks": ["4.3"] },
    { "id": 7, "tasks": ["4.4"] },
    { "id": 8, "tasks": ["4.5"] },
    { "id": 9, "tasks": ["5.1", "6.1"] },
    { "id": 10, "tasks": ["5.2"] },
    { "id": 11, "tasks": ["5.3", "6.2"] },
    { "id": 12, "tasks": ["6.3"] },
    { "id": 13, "tasks": ["6.4", "7.1"] },
    { "id": 14, "tasks": ["7.2"] },
    { "id": 15, "tasks": ["7.3"] },
    { "id": 16, "tasks": ["7.4", "8.1"] },
    { "id": 17, "tasks": ["8.2"] },
    { "id": 18, "tasks": ["8.3", "9.1"] },
    { "id": 19, "tasks": ["10.1"] }
  ]
}
```
