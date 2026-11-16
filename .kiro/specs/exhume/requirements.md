# Requirements Document

## Introduction

Exhume is the first of Revenant's five stages. Given the slug of a dead API, Exhume reads the
tombstone manifest `tombstones/<slug>.toml`, discovers archived captures of the API on every
listed host through the Wayback Machine CDX API, downloads a capped, stratified and
deterministic sample of raw captures, and caches them under `evidence/<slug>/` together with
an index. The later Autopsy stage reads this evidence to infer the API contract.

Exhume follows the Wayback Machine etiquette in `tech.md`, the rules in
`necromancy-ethics.md` and the layout in `structure.md`. This spec also covers the project
scaffold (packaging, package skeleton, first tombstone), because Exhume is the first code in
the repository.

Statements about Archive behaviour in this document refer to the facts F1 to F10 in
Appendix A. Each fact cites the query that was run and an excerpt of its raw output, or is
marked as user-provided.

## Glossary

- **Revenant**: the product and its Python package `revenant/`.
- **Exhume**: the stage implemented by this spec, in the package `revenant/exhume/`.
- **Exhume_CLI**: the `revenant exhume` command of the `revenant` console script.
- **Archive**: the Internet Archive Wayback Machine at base URL `https://web.archive.org`.
- **Archive_Client**: the Exhume component that sends every HTTP request to the Archive,
  applying the User-Agent, the Rate_Limiter and the Retry_Policy.
- **Rate_Limiter**: the Exhume component that spaces the start times of Archive requests.
- **Retry_Policy**: the Exhume component that decides whether a failed Archive request is
  retried and how long to wait before the next attempt.
- **Clock**: an injected source of the current monotonic time, the current UTC time and a
  sleep function. Tests inject a fake Clock.
- **Tombstone**: the TOML manifest `tombstones/<slug>.toml` that describes one dead API
  (fields `slug`, `name`, `died`, `hosts`, `paths`, `mimetypes`).
- **Tombstone_Loader**: the Exhume component that reads and validates a Tombstone.
- **Slug**: the identifier of a dead API in the form `<vendor>-<api>`, for example
  `yahoo-finance-ichart`.
- **Host**: one hostname listed in a Tombstone's `hosts` field.
- **Effective_Mimetypes**: the mimetypes given with `--mimetype`, or the Tombstone's
  `mimetypes` when no `--mimetype` option is given.
- **CDX_Client**: the Exhume component that builds CDX queries and pages through their
  results.
- **CDX_Parser**: the Exhume component that parses one CDX JSON response page into rows and
  an optional Resume_Key.
- **CDX_Printer**: the Exhume component that serializes CDX rows (and an optional
  Resume_Key) back into CDX JSON page format.
- **CDX row**: one record of a CDX listing with the fields `timestamp`, `original`,
  `mimetype`, `statuscode`, `digest` and `length`.
- **Resume_Key**: the opaque pagination token that the CDX API returns, as a single-element
  row after an empty row `[]`, when more results exist (F1, F2).
- **CDX listing**: the complete, deduplicated list of CDX rows for one Host and one pass
  (data pass or error pass), gathered across all pages.
- **Listing_Cache**: the stored CDX listings under `<Evidence_Root>/<slug>/cdx/`.
- **Capture**: one archived HTTP response identified by a CDX row.
- **Data capture**: a Capture from the data pass: status 2xx and a mimetype in the
  Effective_Mimetypes.
- **Error capture**: a Capture from the error pass: status 4xx. Error captures are evidence
  of error behaviour and are never used as data.
- **Error page**: a Data capture whose served body is an HTML page that is not an Offline
  page, although its CDX mimetype is not `text/html`.
- **Error_Evidence**: the set of stored Error captures and Error pages of one Slug, tagged
  `kind="error"` and `kind="error_page"` respectively.
- **Offline page**: the HTML page titled "Internet Archive: Temporarily Offline" that the
  Archive can return under load, sometimes with HTTP 200 (F9).
- **Offline_Detector**: the Exhume component that decides whether a response is an Offline
  page.
- **Content_Validator**: the Exhume component that classifies a fetched body as data, Error
  page or Offline page and verifies its digest.
- **Digest**: the CDX `digest` field, which equals the base32 encoding of the SHA-1 of the
  raw body (F8).
- **Query_Parser**: the Exhume component that parses the query string of a CDX `original`
  URL.
- **Parameter shape**: the classification of a query string into one of `s_only`,
  `empty_range`, `full_range` or `other`, as defined in Requirement 10.
- **Interval**: the value of the `g` query parameter of a Capture, or `none` when `g` is
  absent or empty.
- **Stratum**: the group of Data captures of one Host that share the same capture year
  (first four digits of the timestamp), the same Interval and the same Parameter shape.
- **Selector**: the Exhume component that chooses which Data captures and Error captures to
  download.
- **Cap (N)**: the maximum number of Data captures stored per Host, set by
  `--max-captures`.
- **Error_Cap**: the maximum number of Error_Evidence items stored per Slug: 10.
- **Download attempt**: one fetch of one Capture by the Capture_Fetcher, including all of
  its retries.
- **Ethics_Filter**: the Exhume component that rejects Captures whose `original` URL
  carries an Auth-like parameter.
- **Auth-like parameter**: a query parameter whose name, compared case-insensitively,
  contains one of the substrings `crumb`, `cookie`, `token`, `key`, `session` or `email`.
- **Capture_Fetcher**: the Exhume component that downloads raw Captures.
- **Raw capture URL**: `https://web.archive.org/web/<timestamp>id_/<original>` (F5).
- **Requested timestamp**: the 14-digit timestamp from the CDX row, used in the Raw capture
  URL.
- **Served timestamp**: the 14-digit timestamp of the capture that the Archive actually
  served, which can differ from the Requested timestamp (F6, F7).
- **Evidence_Root**: the directory given by `--evidence-dir`, default `./evidence`.
- **Evidence_Store**: the Exhume component that writes capture files, CDX listings and the
  Index below the Evidence_Root.
- **Index**: the file `<Evidence_Root>/<slug>/index.json` that lists every Capture Exhume
  kept for the Slug.
- **Index entry**: one record in the Index describing one stored Capture.
- **Cached capture**: a selected Capture whose Index entry exists and whose file exists with
  the byte size recorded in the Index entry.
- **Memento-Datetime header**: the `Memento-Datetime` response header that the Archive adds
  when it replays an archived capture, giving the capture time (F7, F10).
- **Permanent rejection**: a Capture rejected for a reason that does not change between
  runs: a response rejected without retry by Requirement 14.7 or 14.8, an Error page
  discarded because the Error_Cap was reached (reason `error_page_over_cap`, Requirement
  18.3). A CDX row excluded under Requirement 7.6 is not a Permanent rejection.
- **Transient rejection**: a Capture rejected because retries were exhausted (connection
  errors, 429, 5xx or Offline page).
- **Atomic write**: writing to a temporary file in the destination directory and then
  renaming it over the destination, so readers see either the old or the new content.
- **Run_Summary**: the Rich table that the Exhume_CLI prints at the end of a run.
- **Config**: the Revenant configuration source that supplies the User-Agent.
- **Scaffold**: the repository packaging, package skeleton, test layout and first Tombstone.

## Requirements

### Requirement 1: Project scaffold

**User Story:** As the Revenant developer, I want a working Python package and test setup, so that every later stage has a place to live and tests run with one command.

#### Acceptance Criteria

1. THE Scaffold SHALL provide a `pyproject.toml` at the repository root that sets `requires-python = ">=3.12"`, lists hatchling in `[build-system] requires` and sets `build-backend = "hatchling.build"`.
2. THE Scaffold SHALL declare a console script named `revenant` that points to `revenant.cli:main`, where `main` runs a Typer application.
3. WHEN the project is installed with `pip install -e ".[dev]"` on Python 3.12, THE Exhume_CLI SHALL make `revenant --help` exit with exit code 0 and list the `exhume` command.
4. THE Scaffold SHALL declare httpx, pydantic constrained to major version 2, typer and rich as runtime dependencies, and SHALL declare an optional dependency group `dev` containing pytest, hypothesis and ruff.
5. THE Scaffold SHALL configure `[tool.pytest.ini_options]` with `addopts = "-m 'not live'"` and SHALL register the marker `live`.
6. WHEN `pytest` runs from the repository root with no arguments, THE Scaffold SHALL make pytest collect the tests under `tests/exhume/`, deselect tests marked `live`, and emit no unknown-marker warning.
7. THE Scaffold SHALL create the package `revenant/` with an `__init__.py` file and the subpackages `exhume`, `autopsy`, `reanimate`, `pulse`, `haunt` and `api`, each a directory directly under `revenant/` containing an `__init__.py` file.
8. THE Scaffold SHALL place Exhume code only in `revenant/exhume/` and `revenant/cli.py`, so that `autopsy`, `reanimate`, `pulse`, `haunt` and `api` each contain exactly one file, `__init__.py`, and no subdirectory.
9. THE Scaffold SHALL create the test directory `tests/exhume/`.
10. THE Scaffold SHALL create `tombstones/yahoo-finance-ichart.toml` with exactly the six fields `slug = "yahoo-finance-ichart"`, `name = "Yahoo Finance historical prices"`, `died = "2017-05"`, `hosts = ["ichart.yahoo.com", "ichart.finance.yahoo.com", "real-chart.finance.yahoo.com"]`, `paths = ["table.csv"]` and `mimetypes = ["text/csv"]`.
11. WHEN the Tombstone_Loader loads the Slug `yahoo-finance-ichart`, THE Tombstone_Loader SHALL accept `tombstones/yahoo-finance-ichart.toml` under the rules of Requirement 2.
12. THE Scaffold SHALL keep `.gitignore` free of any pattern that ignores files under `evidence/` or `.kiro/`, so that `git check-ignore` reports neither `evidence/yahoo-finance-ichart/index.json` nor `.kiro/specs/exhume/requirements.md`.
13. THE Scaffold SHALL omit the directories `web/` and `crypt/` at the repository root.

### Requirement 2: Tombstone loading

**User Story:** As a user, I want Exhume to read a validated manifest of the dead API, so that a typo in the manifest fails fast instead of sending wrong requests to the Archive.

#### Acceptance Criteria

1. WHEN the Exhume_CLI is invoked with a Slug that matches the rule of Requirement 2.2, THE Tombstone_Loader SHALL read `tombstones/<slug>.toml`, resolved against the current working directory as for the default Evidence_Root in Requirement 3.4, and validate the file with a Pydantic model that has the fields `slug`, `name`, `died`, `hosts`, `paths` and `mimetypes`.
2. THE Tombstone_Loader SHALL accept a Slug, both as the command-line argument and as the file's `slug` field, only when the Slug matches the pattern `^[a-z0-9]+(-[a-z0-9]+)+$`.
3. IF the command-line Slug does not match the pattern of Requirement 2.2, THEN THE Exhume_CLI SHALL print an error message that names the Slug and exit with a non-zero exit code without reading any Tombstone file.
4. THE Tombstone_Loader SHALL require all six fields, with `slug`, `name` and `died` as TOML strings and `hosts`, `paths` and `mimetypes` as TOML arrays of strings that each contain at least one entry.
5. IF the Tombstone contains a top-level field other than the six fields of Requirement 2.4, THEN THE Tombstone_Loader SHALL fail validation and report the name of the unknown field.
6. THE Tombstone_Loader SHALL accept a Host only when the Host is a DNS hostname of at most 253 characters made of dot-separated labels of 1 to 63 characters, each label consisting of ASCII letters, digits and hyphens and neither starting nor ending with a hyphen.
7. THE Tombstone_Loader SHALL accept a path only when the path is non-empty, does not start with `/`, has no `/`-separated segment equal to `..`, and contains no `?` or `#` character.
8. IF the `slug` field in the Tombstone differs from the Slug in the file name, THEN THE Tombstone_Loader SHALL fail validation with an error that names both values.
9. IF the Tombstone file is missing, THEN THE Exhume_CLI SHALL print an error message that names the expected file path and exit with a non-zero exit code.
10. IF the Tombstone file cannot be parsed as TOML, THEN THE Exhume_CLI SHALL print an error message that names the file and the line and column of the parse error, and exit with a non-zero exit code.
11. IF the Tombstone fails validation under Requirements 2.2, 2.4 to 2.8 or 2.13, THEN THE Exhume_CLI SHALL print an error message that names the file and every failing field, and exit with a non-zero exit code.
12. IF the command-line Slug is rejected, or the Tombstone file is missing, unparseable or invalid, THEN THE Exhume_CLI SHALL exit before the Archive_Client sends any request.
13. THE Tombstone_Loader SHALL normalise every Host to lowercase, and IF two Hosts are equal after lowercasing, THEN THE Tombstone_Loader SHALL fail validation with an error that names the duplicate Host.

### Requirement 3: Command-line options

**User Story:** As a user, I want to control the sample size, the evidence location, the mimetypes and cache refresh from the command line, so that I can run Exhume on any dead API without editing code.

#### Acceptance Criteria

1. THE Exhume_CLI SHALL accept the command `revenant exhume <slug> [--max-captures N] [--evidence-dir PATH] [--refresh] [--mimetype M ...]`, where `<slug>` is a required positional argument and `--mimetype` may be repeated.
2. WHEN `--max-captures` is not given, THE Exhume_CLI SHALL use 50 as the Cap for every Host.
3. IF the value of `--max-captures` is not an integer of at least 1 (for example `0`, `-3`, `2.5` or `abc`), THEN THE Exhume_CLI SHALL print an error message that names the option and the value, and exit with a non-zero exit code before the Archive_Client sends any request.
4. WHEN `--evidence-dir` is not given, THE Exhume_CLI SHALL use `./evidence` as the Evidence_Root, resolving the default and every relative path against the current working directory.
5. WHERE one or more `--mimetype` options are given, THE Exhume_CLI SHALL use the given values, with duplicates removed, as the Effective_Mimetypes for the data pass of every Host in place of the Tombstone's `mimetypes`.
6. WHERE `--refresh` is given, THE CDX_Client SHALL send CDX queries for both the data pass and the error pass of every Host instead of reusing the Listing_Cache, THE Evidence_Store SHALL replace the stored listings under Requirement 8, and THE Capture_Fetcher SHALL still skip Cached captures under Requirement 22.1.
7. IF the `<slug>` argument is missing or an unknown option is given, THEN THE Exhume_CLI SHALL print an error message that names the missing argument or unknown option, and exit with a non-zero exit code before the Archive_Client sends any request.
8. IF a `--mimetype` value is empty, THEN THE Exhume_CLI SHALL print an error message that names the option and exit with a non-zero exit code before the Archive_Client sends any request.
9. IF the `--evidence-dir` PATH exists and is not a directory, THEN THE Exhume_CLI SHALL print an error message that names PATH and exit with a non-zero exit code before the Archive_Client sends any request.

### Requirement 4: Run summary and exit code

**User Story:** As a user, I want a per-host summary at the end of a run, so that I can see at a glance what Exhume found, fetched and skipped.

#### Acceptance Criteria

1. WHEN a run finishes after the Tombstone, the options, the User-Agent and the Index passed validation, THE Exhume_CLI SHALL print a Run_Summary with exactly one row per Host in the order of the Tombstone's `hosts` field and the columns `found`, `downloaded`, `cached`, `rejected` and `error-evidence`, each holding a non-negative integer.
2. THE Exhume_CLI SHALL report as `found` the number of rows in the Host's data CDX listing after the exclusion of invalid rows under Requirement 7.6 and deduplication under Requirement 8, and before the Ethics_Filter and the Cap are applied, with the same value whether the listing came from the CDX API or from the Listing_Cache.
3. THE Exhume_CLI SHALL report as `downloaded` the number of Captures of the Host, of kind `data`, `error` or `error_page`, that were fetched and stored with an Index entry during the current run.
4. THE Exhume_CLI SHALL report as `cached` the number of selected Captures of the Host, Data captures and Error captures, that were Cached captures and were not fetched during the current run.
5. THE Exhume_CLI SHALL report as `rejected` the number of Captures of the Host, from the data and error listings, excluded during the current run by the Ethics_Filter, by CDX row validation, by a Permanent rejection, by a Transient rejection or by an Error page discarded under Requirement 18.3, counting each Capture at most once and excluding Permanent rejections recorded in earlier runs.
6. THE Exhume_CLI SHALL report as `error-evidence` the number of Index entries of kind `error` or `error_page` for the Host at the end of the run, including entries from earlier runs, so that the sum over all Hosts is at most the Error_Cap of 10.
7. THE Exhume_CLI SHALL count every selected Capture in exactly one of the columns `downloaded`, `cached` and `rejected`.
8. IF the number of Index entries of kind `data` for a Host at the end of the run is less than N, THEN THE Exhume_CLI SHALL mark the Host's row with a shortfall indicator that shows the stored count and N, whatever the cause of the shortfall.
9. WHEN the data pass and the error pass of CDX discovery succeeded for every Host, THE Exhume_CLI SHALL exit with exit code 0, including when a Host has a shortfall or rejections.
10. IF the data pass or the error pass of CDX discovery failed for at least one Host, THEN THE Exhume_CLI SHALL print the Run_Summary, name each failed Host and pass (`data` or `error`), and exit with a non-zero exit code.

### Requirement 5: User-Agent and configuration

**User Story:** As a respectful Archive client, I want every request to identify Revenant, so that the Archive can see who is calling and contact the project.

#### Acceptance Criteria

1. WHEN the Archive_Client sends any request to the Archive, including CDX requests, capture requests, retries and every redirect hop, THE Archive_Client SHALL set the `User-Agent` header to the value read from the Config, byte for byte.
2. THE Archive_Client SHALL send exactly one `User-Agent` header per request, replacing the default User-Agent of the injected httpx client.
3. IF the Config supplies no User-Agent value, THEN THE Config SHALL supply `Revenant/0.1 (+https://github.com/Manthan-1610/revenant)` as the User-Agent.
4. WHEN a run starts, THE Exhume_CLI SHALL validate the User-Agent before the Archive_Client sends any request.
5. IF the User-Agent contains a substring matching the pattern `[^\s@]+@[^\s@]+\.[^\s@]+`, THEN THE Exhume_CLI SHALL print an error message stating that the User-Agent contains an email address, and exit with a non-zero exit code before the Archive_Client sends any request.
6. IF the User-Agent is empty, consists only of whitespace, or contains CR, LF or any other ASCII control character, THEN THE Exhume_CLI SHALL print an error message and exit with a non-zero exit code before the Archive_Client sends any request.

### Requirement 6: CDX discovery of Data captures

**User Story:** As the Autopsy stage, I want a complete list of unique archived data responses for every host, so that the sample can be drawn from the whole history of the API.

#### Acceptance Criteria

1. WHEN discovering Data captures for a Host and a path, THE CDX_Client SHALL send a GET request to `https://web.archive.org/cdx/search/cdx` with the URL-encoded parameters `url=<host>/<path>*`, `output=json`, `collapse=digest`, `filter=statuscode:2..`, `fl=timestamp,original,mimetype,statuscode,digest,length`, `limit=<page size>` and `showResumeKey=true`, where the page size is a design decision of at most 1000 (F1, F3, F4).
2. WHEN discovering Data captures, THE CDX_Client SHALL add `filter=mimetype:<pattern>` parameters whose patterns match every Effective_Mimetype and no other mimetype (F1).
3. WHEN a data-pass row has a mimetype that is not in the Effective_Mimetypes, THE CDX_Client SHALL leave the row out of the listing and count the row neither as found nor as rejected.
4. WHEN the CDX_Parser returns a Resume_Key for a page, THE CDX_Client SHALL request the next page with the same parameters plus `resumeKey=<Resume_Key>`, with the key unchanged apart from URL-encoding (F2).
5. WHEN the CDX_Parser returns no Resume_Key for a page, THE CDX_Client SHALL treat the listing for that Host, path and pass as complete and send no further request for it, including when the listing has zero rows (F3).
6. IF a Resume_Key repeats a key already used for the same Host, path and pass, THEN THE CDX_Client SHALL stop paginating and mark discovery for that Host and pass as failed.
7. WHEN a Tombstone lists more than one path, THE CDX_Client SHALL query the paths in Tombstone order and combine their rows into one CDX listing for the Host and pass, deduplicated under Requirement 8.
8. WHEN a complete listing for a Host and pass has zero rows, THE CDX_Client SHALL treat discovery for that Host and pass as successful, and THE Exhume_CLI SHALL report `found` as 0 for a data listing.
9. IF a CDX request for any path receives a non-retryable failure under Requirement 16.7, fails after 5 attempts under Requirement 16.4, or returns a body that the CDX_Parser rejects under Requirement 7.5, THEN THE CDX_Client SHALL mark discovery for that Host and pass as failed, discard the rows gathered for that Host and pass, and send no further CDX request for the remaining paths of that Host and pass.
10. IF discovery for a Host and pass failed, THEN THE CDX_Client SHALL continue with the remaining passes and Hosts in Tombstone order.
11. THE CDX_Client SHALL accept rows in any timestamp order, and SHALL reject no row and end no pagination because of row order (F1).

### Requirement 7: CDX response parsing and printing

**User Story:** As the Revenant developer, I want a strict parser for CDX JSON pages, so that pagination and field mapping are correct for any page the Archive returns.

#### Acceptance Criteria

1. WHEN given a CDX JSON page whose first row is a header containing each of `timestamp`, `original`, `mimetype`, `statuscode`, `digest` and `length` exactly once in any order, THE CDX_Parser SHALL map every following data row to a CDX row by header field name, so that permuting the header and the data columns identically yields identical CDX rows (F1).
2. WHEN a CDX JSON page ends with an empty row `[]` immediately followed by a final row of exactly one non-empty string, THE CDX_Parser SHALL return that string unchanged as the Resume_Key and SHALL exclude both rows from the data rows (F1, F2).
3. WHEN a CDX JSON page has no `[]` row after the header, THE CDX_Parser SHALL return every row after the header as data rows in page order and no Resume_Key (F3).
4. WHEN a CDX JSON page is an empty JSON array `[]` or contains only the header row, THE CDX_Parser SHALL return zero data rows and no Resume_Key.
5. IF a CDX page is not valid JSON, is not a JSON array of arrays of strings, has a first row that fails the header rule of Requirement 7.1, has a data row whose length differs from the header length, has a `[]` row anywhere other than immediately before the final row, or has a `[]` row followed by a final row that does not hold exactly one non-empty string, THEN THE CDX_Parser SHALL return a parse error that names the violated rule and the zero-based index of the offending row (or the whole page), and SHALL return no rows and no Resume_Key for that page.
6. IF a parsed CDX row has a `timestamp` that is not exactly 14 ASCII digits or a `digest` that is not exactly 32 characters from the base32 alphabet `A-Z2-7`, THEN THE CDX_Client SHALL exclude that row from the listing in every run, keep the other rows, and add 1 per excluded row to the Host's `rejected` count under Requirement 4.5, without recording the row as a Permanent rejection in the Index.
7. THE CDX_Printer SHALL serialize a header (an ordering of the six field names), a list of CDX rows and an optional Resume_Key into a CDX JSON page in the format of F1: the header first, then one array of strings per CDX row in the given order with values in header order, then a `[]` row and a one-element Resume_Key row only when a Resume_Key is given.
8. FOR ALL lists of zero or more CDX rows that pass Requirement 7.6, all orderings of the six header field names and all optional non-empty Resume_Keys, printing with the CDX_Printer and then parsing with the CDX_Parser SHALL return the same rows in the same order and the same Resume_Key, or no Resume_Key when none was given (round-trip property).

### Requirement 8: CDX deduplication and listing cache

**User Story:** As a respectful Archive client, I want each CDX listing fetched once and deduplicated, so that later runs do not repeat expensive queries and the sample contains no duplicate bodies.

#### Acceptance Criteria

1. WHEN the last page, with no Resume_Key (F3), has been received for every path of a Host in one pass, THE CDX_Client SHALL treat the CDX listing for that Host and pass as complete.
2. WHEN a CDX listing is complete, THE CDX_Client SHALL keep exactly one row per Digest across all pages and paths of that Host and pass, without considering rows excluded under Requirement 7.6.
3. WHEN several rows share a Digest, THE CDX_Client SHALL keep the row with the smallest timestamp by 14-digit string comparison and, among rows with equal timestamps, the row with the lexicographically smallest `original`.
4. WHEN a data CDX listing for a Host is complete, THE Evidence_Store SHALL write the validated, deduplicated listing with an Atomic write to `<Evidence_Root>/<slug>/cdx/<host>.json`, together with the query parameters that produced the listing (paths, status filter and Effective_Mimetypes).
5. IF pagination for any path of a Host and pass stops before the last page, because retries were exhausted, the CDX_Parser rejected a page or the run was interrupted, THEN THE Evidence_Store SHALL write no partial listing and SHALL leave any previously stored complete listing for that Host and pass byte-identical.
6. WHILE `--refresh` is not given, WHEN a stored listing exists for a Host and pass with query parameters equal to the current query parameters, THE CDX_Client SHALL use the stored listing and send 0 CDX requests for that Host and pass, where equal means identical status filter strings, equal sets of paths and equal sets of Effective_Mimetypes, with order ignored.
7. WHILE `--refresh` is not given, IF a stored listing's recorded query parameters differ from the current query parameters, THEN THE CDX_Client SHALL query the CDX API and, when the new listing is complete, THE Evidence_Store SHALL replace the stored listing under Requirement 8.4.
8. IF a stored listing is unreadable, unparseable or lacks recorded query parameters, THEN THE CDX_Client SHALL treat the listing as absent, query the CDX API and continue the run.
9. THE Evidence_Store SHALL omit from every stored listing the rows rejected by the Ethics_Filter and SHALL store only the count of such rows, so that no `original` URL with an Auth-like parameter is written anywhere under the Evidence_Root, and THE Exhume_CLI SHALL compute `found` (Requirement 4.2) as the number of stored rows plus that count, so that `found` is the same for cached and fresh listings.

### Requirement 9: Error evidence discovery

**User Story:** As the Autopsy stage, I want a few archived error responses, so that the revenant can reproduce how the dead API answered bad requests.

#### Acceptance Criteria

1. WHEN discovering Error captures for a Host and a path, THE CDX_Client SHALL send a separate CDX query to the same endpoint with the same `url`, `output`, `collapse`, `fl`, `limit` and `showResumeKey` parameters as Requirement 6.1, differing only in the status filter `filter=statuscode:4..` and the absence of any mimetype filter, so that 4xx rows of any mimetype, including `text/html`, are listed (F3, F4).
2. THE CDX_Client SHALL apply the pagination, path combination and failure rules of Requirement 6, the parsing rules of Requirement 7 and the deduplication and Listing_Cache rules of Requirement 8 to the error pass, and THE Evidence_Store SHALL store the error listing under `<Evidence_Root>/<slug>/cdx/` in a file distinct from the data listing file, with the recorded query parameters (paths, status filter `4..` and no mimetypes).
3. THE Selector SHALL keep the total number of Error_Evidence items, of kind `error` or `error_page`, in the Index of a Slug at or below the Error_Cap of 10, counting all Hosts and earlier runs.
4. WHEN the data downloads of all Hosts are complete, THE Selector SHALL compute the remaining Error_Evidence slots as 10 minus the number of Error_Evidence items in the Index, and SHALL fill the slots in rounds, each round taking the next Error capture candidate from each Host in Tombstone order and skipping Hosts that have no remaining candidate or whose error pass failed.
5. WHEN an Error capture is stored, THE Evidence_Store SHALL tag the Index entry with `kind="error"` and derive the file extension under Requirement 20.2.
6. THE Selector SHALL exclude Error captures and Error pages from the Data capture sample and the Cap of every Host.
7. THE Selector SHALL order a Host's Error capture candidates by ascending Requested timestamp and then ascending Digest, independent of listing order, and SHALL exclude from the candidates the Captures rejected by the Ethics_Filter, the rows excluded under Requirement 7.6, the recorded Permanent rejections (Requirement 12.7) and the Cached captures, which already count toward the Error_Cap under Requirement 9.3.
8. WHEN the remaining Error_Evidence slots reach 0, no Error capture candidate remains on any Host, or 20 Error capture Download attempts have been made in the run (Requirement 12.8), THE Selector SHALL stop selecting Error captures, and THE Capture_Fetcher SHALL send no further Error capture request in that run.

### Requirement 10: Query string parsing and Parameter shape

**User Story:** As the Selector, I want every capture's request parameters parsed reliably, so that the sample covers the different ways old clients called the API.

#### Acceptance Criteria

1. WHEN given a CDX `original` URL, including a URL with an explicit port such as `:80` (F1), THE Query_Parser SHALL take the query string as the part after the first `?` and before any `#`, and SHALL return the query parameters as name-value pairs with `%XX` escapes in names and values decoded as UTF-8.
2. THE Query_Parser SHALL treat a parameter with an empty value (`a=`) or without `=` (`a`) as present with the empty string as its value.
3. THE Query_Parser SHALL compare parameter names case-sensitively for Parameter shape classification, while the Ethics_Filter compares names case-insensitively under Requirement 13.2.
4. IF a parameter name occurs more than once in a query string, THEN THE Query_Parser SHALL use the first occurrence for the Parameter shape, the Interval and the value of `s`.
5. THE Query_Parser SHALL produce the same parameter mapping, Parameter shape and Interval for query strings that differ only in parameter order (F1).
6. THE Query_Parser SHALL produce the same value for `s` whether the symbol is raw (`s=^DJI`) or percent-encoded (`s=%5EDJI`) (F9).
7. THE Query_Parser SHALL classify a query string as `s_only` when `s` is present with any value, none of `a`, `b`, `c`, `d`, `e`, `f` and `g` is present, and every other parameter name is `ignore`.
8. THE Query_Parser SHALL classify a query string as `empty_range` when each of the parameters `a`, `b`, `c`, `d`, `e`, `f` and `g` is present and every one of their values is empty, whatever other parameters are present.
9. THE Query_Parser SHALL classify a query string as `full_range` when each of the parameters `a`, `b`, `c`, `d`, `e`, `f` and `g` is present and every one of their values is non-empty, whatever other parameters are present, so that both query strings of F1 classify as `full_range`.
10. THE Query_Parser SHALL classify every query string that is not `s_only`, `empty_range` or `full_range` as `other`, so that each query string has exactly one Parameter shape.
11. THE Query_Parser SHALL report the Interval as the decoded value of `g` with its letter case preserved (for example `d`, `w`, `m` or `v`), or `none` when `g` is absent or empty.
12. IF a CDX `original` URL has no `?` or an empty query string, THEN THE Query_Parser SHALL return an empty parameter mapping, the Parameter shape `other` and the Interval `none`.
13. IF a CDX `original` URL cannot be parsed, because it has no scheme, no host or a port that is not an integer from 0 to 65535, THEN THE Query_Parser SHALL classify the Capture with the Parameter shape `other` and the Interval `none`, and THE Selector SHALL keep the Capture as a candidate unless the Ethics_Filter rejects the Capture under Requirement 13.7, so that this fallback applies only when the URL has no query string to inspect or its query string was parsed successfully.

### Requirement 11: Stratified deterministic selection

**User Story:** As the Autopsy stage, I want a small sample that spans years, intervals and request shapes, so that contract inference sees every variant of the API's behaviour.

#### Acceptance Criteria

1. WHEN selecting Data captures for a Host, THE Selector SHALL choose exactly min(N, E) Captures from the candidates, where the candidates are the rows of the Host's deduplicated data CDX listing that pass the Ethics_Filter and Requirement 7.6 and are not recorded Permanent rejections (Requirement 12.7), and E is the number of candidates.
2. THE Selector SHALL place each candidate in exactly one Stratum keyed by capture year (first four digits of the Requested timestamp), Interval (Requirement 10.11) and Parameter shape (Requirements 10.7 to 10.10), with unparseable `original` URLs placed under `other` and `none` (Requirement 10.13).
3. WHEN N is at least I, the number of distinct Intervals among the candidates, THE Selector SHALL select at least one Capture for every distinct Interval.
4. WHEN N is at least I + P, where P is the number of distinct Parameter shapes among the candidates, THE Selector SHALL cover every distinct Interval and every distinct Parameter shape.
5. WHEN N is at least I + P + Y, where Y is the number of distinct capture years among the candidates, THE Selector SHALL cover every distinct Interval, every distinct Parameter shape and every distinct capture year.
6. WHEN N is at least the number of non-empty Strata, THE Selector SHALL select at least one Capture from every non-empty Stratum.
7. THE Selector SHALL produce the same set of selected Captures, identified by (Requested timestamp, Digest), for the same candidate set and the same N, independent of the order of the rows and of the process, by using a fixed seed and a canonical ordering of candidates by ascending timestamp and then ascending Digest.
8. THE Selector SHALL select at most one Capture per Digest.
9. IF E is 0 for a Host, THEN THE Selector SHALL select zero Captures, THE Capture_Fetcher SHALL make no Data capture Download attempt for the Host, and THE Exhume_CLI SHALL report the shortfall under Requirement 4.8.
10. THE Selector SHALL compute each Host's selection from that Host's candidates only.

### Requirement 12: Backfill of rejected selections

**User Story:** As a user, I want rejected captures replaced by similar ones, so that a few bad captures do not shrink the sample, without Exhume looping forever.

#### Acceptance Criteria

1. WHEN a selected Data capture receives a Permanent rejection or a Transient rejection, or is classified as an Error page (stored under Requirement 18.2 or discarded under Requirement 18.3), THE Selector SHALL replace the Capture with the first unselected candidate of the same Stratum, in the canonical order of Requirement 11.7, whose Digest differs from every Digest already selected for the Host in the run.
2. IF the Stratum of a replaced Data capture has no such candidate, THEN THE Selector SHALL take the replacement from another Stratum of the same Host by the deterministic rule of Requirement 11.
3. THE Selector SHALL select each Capture at most once per run, so that a replaced Capture is never selected again as a replacement in the same run.
4. THE Capture_Fetcher SHALL make at most 2×N Data capture Download attempts per Host per run, counting initial selections, replacements and attempts that yield Error pages, counting each Download attempt once regardless of its retries, and not counting Cached captures.
5. WHEN the limit of 2×N Download attempts is reached, or no unselected candidate remains in any Stratum of the Host, THE Selector SHALL stop backfilling for the Host, THE Capture_Fetcher SHALL send no further Data capture request for the Host, and THE Exhume_CLI SHALL report the shortfall under Requirement 4.8.
6. WHEN a selected Error capture receives a Permanent rejection or a Transient rejection, THE Selector SHALL replace the Error capture with the next Error capture by the rule of Requirement 9.4.
7. WHEN a Capture receives a Permanent rejection, THE Evidence_Store SHALL record the Capture's Host, Requested timestamp, Digest and rejection reason in the Index, and THE Selector SHALL exclude recorded Permanent rejections from the candidates of every later run.
8. THE Capture_Fetcher SHALL make at most 20 Error capture Download attempts per Slug per run, counting each Download attempt once regardless of its retries and not counting Cached captures, and WHEN 20 attempts are reached, the Index holds 10 Error_Evidence items, or no unselected Error capture remains, THE Selector SHALL stop selecting Error captures.
9. WHEN a Capture receives a Transient rejection, THE Evidence_Store SHALL write no Index entry and no Permanent rejection record for the Capture, so that the Capture is a candidate again in the next run.
10. WHEN Exhume runs twice with the same candidates, the same N and the same set of rejected and Error-page Captures, THE Selector SHALL produce the same sequence of selections and replacements in both runs.

### Requirement 13: Ethics filter

**User Story:** As the project owner, I want captures of authenticated requests excluded, so that Revenant never stores credentials or personal data found in archived URLs.

#### Acceptance Criteria

1. IF a row of a deduplicated listing (Requirement 8.2), from the data pass or the error pass, has an `original` URL with at least one Auth-like parameter, THEN THE Ethics_Filter SHALL reject the Capture before selection, excluding the Capture from E (Requirement 11.1), from Error capture selection (Requirement 9.4) and from backfill (Requirement 12).
2. THE Ethics_Filter SHALL take parameter names from the Query_Parser (Requirement 10.1), percent-decoded, and match them case-insensitively by substring, counting parameters with an empty value or without `=`, so that `crumb`, `X-Crumb`, `apiKey`, `sessionid`, `EMAIL`, `%63rumb` and `keyword` are all matched.
3. WHEN the Ethics_Filter rejects a Capture, THE Capture_Fetcher SHALL send no request for the Capture, and THE Evidence_Store SHALL write no capture file and no Index entry for the Capture and SHALL store the `original` URL neither in the Index, nor in the Permanent rejection records (Requirement 12.7), nor in the stored listings (Requirement 8.9).
4. THE Ethics_Filter SHALL accept every Capture whose `original` URL has no Auth-like parameter, including URLs with no query string and URLs where the substrings appear only in parameter values (for example `s=TOKEN`), in the path or in the fragment.
5. THE Exhume_CLI SHALL count each Ethics_Filter rejection exactly once in the Host's `rejected` column, for both passes and including runs that use a cached listing, and SHALL count a row that also fails Requirement 7.6 once.
6. THE Ethics_Filter SHALL make the same decision for the same `original` URL in every run, independent of `--refresh`, `--max-captures` and `--mimetype`.
7. IF the query string of an `original` URL cannot be parsed by the Query_Parser, THEN THE Ethics_Filter SHALL reject the Capture with the same effects as Requirements 13.1, 13.3 and 13.5, and this rejection SHALL take precedence over the candidate fallback of Requirement 10.13.

### Requirement 14: Raw capture download

**User Story:** As the Autopsy stage, I want the original response bytes exactly as archived, so that contract inference sees the real dead API and not the Archive's wrapper.

#### Acceptance Criteria

1. WHEN fetching a Capture, THE Capture_Fetcher SHALL send a GET request through the Archive_Client to the Raw capture URL `https://web.archive.org/web/<Requested timestamp>id_/<original>`, with `<original>` copied character for character including any `:80`, and with redirects followed (F5, F6).
2. WHEN a Capture is stored, THE Evidence_Store SHALL record `requested_timestamp`, `served_timestamp` and `final_url` in the Index entry, recording both timestamps even when they are equal (F6).
3. WHEN the path of the final URL after redirects starts with `/web/` followed by exactly 14 digits and `id_/`, THE Capture_Fetcher SHALL record those 14 digits as the Served timestamp, even when a Memento-Datetime header is present (F6).
4. IF the final URL has no such timestamp, THEN THE Capture_Fetcher SHALL take the Served timestamp from the Memento-Datetime header parsed as an HTTP date and converted to UTC in the form `YYYYMMDDhhmmss` (for example `Fri, 13 Dec 2013 17:44:36 GMT` becomes `20131213174436`, F7), and SHALL record a null Served timestamp, which is not a rejection reason, when the header is absent or unparseable.
5. WHEN a Data capture's final response has a 2xx status and is not an Offline page, THE Capture_Fetcher SHALL pass the body to the Content_Validator.
6. WHEN an Error capture's final response has a status equal to the CDX `statuscode`, including 429, carries a Memento-Datetime header and is not an Offline page, THE Capture_Fetcher SHALL pass the body to the Content_Validator as error evidence (F10, Requirement 16.6).
7. IF a Data capture's final response has a 4xx status other than 429, THEN THE Capture_Fetcher SHALL make the Capture a Permanent rejection after that single attempt, without retrying and without passing the body to the Content_Validator, regardless of the Memento-Datetime header (Requirement 16.7).
8. IF an Error capture's final response has a 4xx status other than 429 and either the status differs from the CDX `statuscode` or the response carries no Memento-Datetime header, THEN THE Capture_Fetcher SHALL make the Capture a Permanent rejection after that single attempt, without retrying and without passing the body to the Content_Validator (F10).
9. THE Archive_Client SHALL send requests one at a time, starting a request, including a retry or a redirect hop, only after the previous response has been fully received or has failed.
10. THE Archive_Client SHALL take the httpx client and the Clock as injected dependencies, send every request through the injected httpx client, and wait only through the injected Clock.
11. THE Capture_Fetcher SHALL pass the body to the Content_Validator byte for byte as received, without charset decoding, newline conversion or trimming.
12. IF a final response is a retryable failure under Requirement 16.1, THEN THE Capture_Fetcher SHALL pass the response to the Retry_Policy and pass no body to the Content_Validator.

### Requirement 15: Rate limiting

**User Story:** As a respectful Archive client, I want requests spaced out, so that Revenant never adds load spikes to the Archive.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL ensure that at least 1 second of Clock monotonic time passes between the start times of any two Archive requests in one run, where the start time is the Clock reading taken immediately before the request is handed to the httpx client.
2. THE Rate_Limiter SHALL apply one shared spacing sequence to data and error CDX requests, Data capture and Error capture requests, retries and every redirect hop, across all Hosts.
3. WHEN the previous request started less than 1 second earlier, THE Rate_Limiter SHALL call the Clock's sleep function once with the remaining time.
4. WHEN at least 1 second has elapsed since the previous request started, including after a backoff wait, THE Rate_Limiter SHALL make no sleep call.
5. WHEN the first request of a run is sent, THE Rate_Limiter SHALL make no sleep call.
6. THE Rate_Limiter SHALL wait only before requests that are actually sent, so that Cached captures (Requirement 22.1), reused listings (Requirement 8.6) and Ethics_Filter rejections (Requirement 13.3) cause no sleep call.
7. WHILE waiting to respect the spacing, THE Rate_Limiter SHALL wait only through the Clock's sleep function and through no other sleep.

### Requirement 16: Retries and backoff

**User Story:** As a user, I want transient Archive failures retried with backoff, so that a busy Archive slows Exhume down instead of breaking the run.

#### Acceptance Criteria

1. WHEN an attempt ends with a connection error, a timeout raised by the injected httpx client, a final status of 429 or 500 to 599, or an Offline page (Requirement 17), THE Retry_Policy SHALL classify the failure as retryable, except where Requirement 16.6 classifies the response as a success.
2. THE Retry_Policy SHALL make at most 5 attempts per Archive request, including the first attempt, where one attempt is the request to the initial URL with all of its redirect hops and a failure on any hop fails the attempt.
3. WHEN a retryable failure occurs on attempt k (k = 1 to 4), THE Retry_Policy SHALL wait min(60, max(2 × 2^(k−1), R)) seconds before attempt k+1 (2, 4, 8 and 16 seconds when R is 0), where R is the `Retry-After` header value as non-negative integer seconds, or as an HTTP date minus the current UTC time supplied by the Clock, and R is 0 when the header is absent, unparseable, negative or not in the future, or when no response was received.
4. IF a retryable failure occurs on attempt 5, THEN THE Retry_Policy SHALL make no further attempt, THE Capture_Fetcher SHALL make the Capture a Transient rejection with no Permanent rejection record, and THE CDX_Client SHALL mark discovery for the Host and pass as failed (Requirement 6.9).
5. WHEN an Error capture's final response has a 4xx status other than 429 and Requirement 16.6 does not apply, THE Retry_Policy SHALL classify the response as a non-retryable failure.
6. WHEN an Error capture's final response satisfies Requirement 14.6 and is not an Offline page, THE Retry_Policy SHALL classify the response as a success, including when its status is 429.
7. WHEN a CDX request or a Data capture request receives a final 4xx status other than 429, THE Retry_Policy SHALL classify the response as a non-retryable failure regardless of the Memento-Datetime header.
8. WHEN a response is classified as a non-retryable failure, THE Retry_Policy SHALL make no further attempt, THE Capture_Fetcher SHALL make a Capture a Permanent rejection (Requirements 14.7 and 14.8), and THE CDX_Client SHALL mark CDX discovery for the Host and pass as failed (Requirement 6.9).
9. WHILE waiting between attempts, THE Retry_Policy SHALL wait through the Clock's sleep function, and THE Rate_Limiter SHALL also apply its spacing to the retries.

### Requirement 17: Offline page detection

**User Story:** As the Autopsy stage, I want Archive outage pages kept out of the evidence, so that contract inference never mistakes the Archive's error page for the dead API's response.

#### Acceptance Criteria

1. THE Offline_Detector SHALL classify a response as an Offline page only when the response is HTML under Requirement 17.2 and the text of its first `<title>` element contains `Temporarily Offline` case-sensitively (F9), where the title text is the text between the first `<title` opening tag, which may carry attributes, and the next `</title>`, with tag names compared case-insensitively.
2. THE Offline_Detector SHALL treat a response as HTML when the media type of its `Content-Type` header, compared case-insensitively and ignoring parameters such as `charset`, is `text/html` (F10), or when its body, after removing one leading UTF-8 byte order mark and all leading whitespace, starts with `<!DOCTYPE` or `<html` compared case-insensitively.
3. THE Offline_Detector SHALL give the same classification regardless of the HTTP status code, including 200, 404, 429 and 503 (F9).
4. IF an HTML response has no `<title>` element, has an unclosed `<title` tag, or has a first title text without `Temporarily Offline`, THEN THE Offline_Detector SHALL classify the response as not an Offline page.
5. IF a response is not HTML under Requirement 17.2, THEN THE Offline_Detector SHALL classify the response as not an Offline page, including every CSV, JSON or XML body served without a `text/html` media type.
6. WHEN a response to a CDX request, a Data capture request or an Error capture request is received, THE Archive_Client SHALL run the Offline_Detector before the CDX_Parser, the Content_Validator or the status match of Requirement 14.6.
7. WHEN the Offline_Detector classifies a response as an Offline page, THE Retry_Policy SHALL treat the response as a retryable failure under Requirements 16.1 to 16.3, and Requirement 16.4 SHALL apply after 5 attempts.
8. THE Evidence_Store SHALL write no Offline page body to any capture file, Listing_Cache file or Index entry, and THE Exhume_CLI SHALL count no Offline page as a Data capture, an Error capture, an Error page or an Error_Evidence item.

### Requirement 18: Content validation and Error pages

**User Story:** As the Autopsy stage, I want HTML error pages served in place of data marked as such, so that data evidence contains only real data responses.

#### Acceptance Criteria

1. WHEN a Data capture body is passed to the Content_Validator, its CDX mimetype is not `text/html`, and the body is HTML under Requirement 17.2 and not an Offline page, THE Content_Validator SHALL classify the body as an Error page.
2. WHEN the Content_Validator classifies a body as an Error page and the Index holds fewer than 10 Error_Evidence items at that moment, counting all Hosts and earlier runs, THE Evidence_Store SHALL store the body with `kind="error_page"` and the file extension `html`.
3. IF the Content_Validator classifies a body as an Error page and the Index already holds 10 Error_Evidence items, THEN THE Evidence_Store SHALL discard the body, write no capture file and no Index entry for a stored Capture, and record the Capture as a Permanent rejection with reason `error_page_over_cap` (Requirement 12.7), and THE Exhume_CLI SHALL count the Capture as rejected.
4. THE Selector SHALL count stored Error pages toward the Error_Cap, and not toward the Cap of the Host or the stored count of the shortfall indicator (Requirement 4.8).
5. WHEN a body is neither an Offline page nor an Error page, THE Content_Validator SHALL classify the body as data for a Data capture, including a Data capture with CDX mimetype `text/html` and an HTML body, and as error evidence for an Error capture.
6. THE Content_Validator SHALL classify no Error capture body as an Error page (F4, F10).
7. WHEN a Data capture is classified as an Error page, stored or discarded, THE Capture_Fetcher SHALL count the fetch as one Download attempt toward the limit of 2×N (Requirement 12.4), and THE Selector SHALL backfill the Capture under Requirement 12.1.

### Requirement 19: Digest verification

**User Story:** As the Autopsy stage, I want to know whether each stored body matches the Archive's digest, so that I can trust or discount individual captures.

#### Acceptance Criteria

1. THE Content_Validator SHALL compute the digest of a body as the RFC 4648 base32 encoding, in upper case and without `=` padding, of the SHA-1 hash of the exact bytes written to the capture file, for bodies of 0 or more bytes.
2. THE Content_Validator SHALL produce a digest of exactly 32 characters from the alphabet `A-Z2-7`.
3. WHEN given the 15479-byte body of F5, THE Content_Validator SHALL compute the digest `M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY`, equal to the CDX digest of the same capture in F1 (F8).
4. WHEN a Capture of any kind is stored, THE Evidence_Store SHALL record `digest_verified: true` in the Index entry if the computed digest equals the CDX Digest exactly and case-sensitively, and `digest_verified: false` otherwise.
5. IF the computed digest differs from the CDX Digest, THEN THE Evidence_Store SHALL still store the Capture and its Index entry, and THE Capture_Fetcher SHALL neither retry the Capture nor treat it as a Permanent or Transient rejection.
6. IF the computed digest differs from the CDX Digest, THEN THE Exhume_CLI SHALL count the Capture as downloaded and not as rejected, and THE Selector SHALL count the Capture toward the Cap of the Host for kind `data` or toward the Error_Cap for kinds `error` and `error_page`.
7. WHEN a selected Capture is a Cached capture, THE Evidence_Store SHALL leave the `digest_verified` value of its Index entry unchanged.

### Requirement 20: Evidence file layout

**User Story:** As the Autopsy stage, I want captures stored at predictable paths, so that I can find every capture of a host without a database.

#### Acceptance Criteria

1. THE Evidence_Store SHALL store every Capture of kind `data`, `error` or `error_page` at `<Evidence_Root>/<slug>/<host>/<Requested timestamp>-<Digest>.<ext>`, where `<host>` is the lowercased Host (Requirement 2.13), `<Requested timestamp>` is the 14-digit CDX timestamp and `<Digest>` is the 32-character CDX digest.
2. THE Evidence_Store SHALL derive `<ext>` from the CDX mimetype, compared case-insensitively and ignoring parameters after `;`: `text/csv` maps to `csv`, `text/xml` and `application/xml` map to `xml`, `application/json` maps to `json`, `text/html` maps to `html`, and every other mimetype, including an empty one, maps to `bin`, except that Error pages always use `html` (Requirement 18.2).
3. THE Evidence_Store SHALL produce file paths that differ as strings for any two (Host, Requested timestamp, Digest) triples that differ in any component, given Hosts validated under Requirements 2.6 and 2.13 and timestamps and digests validated under Requirement 7.6.
4. THE Evidence_Store SHALL write a file only when its absolute path lies inside the resolved Evidence_Root after resolving `.`, `..` and symbolic links.
5. IF a computed file path would resolve outside the Evidence_Root, THEN THE Evidence_Store SHALL refuse to write the file, create no file or temporary file outside the Evidence_Root, add no Index entry, and report an error that names the Host and the Requested timestamp.
6. THE Evidence_Store SHALL write every capture file with an Atomic write whose temporary file is in the destination directory.
7. WHEN the directory `<Evidence_Root>/<slug>/<host>/` does not exist, THE Evidence_Store SHALL create the directory, including its parents, before writing.
8. IF an Atomic write fails before the rename, THEN THE Evidence_Store SHALL leave any existing destination file unchanged, remove the temporary file, add or change no Index entry, and report an error that names the destination.

### Requirement 21: Evidence Index

**User Story:** As the Autopsy stage, I want one index of everything Exhume kept for a slug, so that I can load the evidence with its provenance in a single read.

#### Acceptance Criteria

1. THE Evidence_Store SHALL maintain exactly one Index per Slug at `<Evidence_Root>/<slug>/index.json`, defined by a Pydantic model with two separate collections: the Index entries of stored Captures and the Permanent rejection records (Requirement 12.7).
2. THE Index SHALL key Index entries and Permanent rejection records by `<host>/<Requested timestamp>-<Digest>`, with at most one item per key in each collection.
3. THE Index entry SHALL contain `host`; `kind` (one of `data`, `error`, `error_page`); `requested_timestamp`; `original`, `mimetype`, `statuscode`, `digest` and `length` from the CDX row; `served_timestamp` (14 digits, or null under Requirement 14.4); `final_url`; `path` (relative to the Evidence_Root, with `/` separators, following the layout of Requirement 20.1); `size` (bytes, equal to the file size); `sha256` (64 lowercase hex characters); `content_type` (the response `Content-Type` value, or null); `digest_verified` (Requirement 19.4); and `fetched_at` (UTC ISO 8601).
4. THE Index SHALL record the CDX `length` field as given by the CDX API, separate from `size`, because the CDX `length` differs from the body size (F1, F8).
5. WHEN a Capture is stored or a Permanent rejection is recorded, THE Evidence_Store SHALL rewrite the Index with an Atomic write before the next Download attempt starts.
6. THE Evidence_Store SHALL serialize the Index deterministically, with keys sorted, UTF-8 encoding, a fixed indentation, exactly one trailing newline, and no run-level fields that change between runs other than the entries and records written in the current run, so that equal Index contents produce identical bytes.
7. FOR ALL valid Index objects, serializing to JSON and then parsing SHALL produce an equal Index object (round-trip property).
8. THE Index SHALL hold in each Permanent rejection record the fields `host`, `requested_timestamp`, `digest` and `reason`, no body, and no record for an Ethics_Filter rejection (Requirement 13.3).
9. WHEN `index.json` does not exist at the start of a run, THE Evidence_Store SHALL treat the Index as empty.
10. IF `index.json` exists but is not valid UTF-8 JSON or fails validation against the Index model, THEN THE Exhume_CLI SHALL print an error message that names the file, leave the file unchanged, and exit with a non-zero exit code before the Archive_Client sends any request.

### Requirement 22: Caching and idempotence

**User Story:** As a respectful Archive client, I want reruns to skip captures already on disk, so that an interrupted or repeated run never fetches the same capture twice.

#### Acceptance Criteria

1. WHEN the key (Requirement 21.2) of a selected Capture belongs to a Cached capture, THE Capture_Fetcher SHALL send no Archive request for the Capture, checking only the existence and byte size of the file.
2. WHEN a selected Capture is a Cached capture, THE Exhume_CLI SHALL count the Capture as cached and not as downloaded, and THE Selector SHALL count the Capture toward the Cap of the Host for kind `data` or toward the Error_Cap for Error_Evidence.
3. IF a selected Capture has an Index entry but the file at its `path` is missing or has a different size, THEN THE Capture_Fetcher SHALL fetch the Capture again as a Download attempt (Requirement 12.4 or 12.8), and if the Capture is stored, THE Evidence_Store SHALL replace the Index entry and THE Exhume_CLI SHALL count the Capture as downloaded.
4. WHEN Exhume runs a second time with the same Tombstone, the same arguments and the same Listing_Cache, and the first run had no Transient rejections and no failed CDX discovery, THE Capture_Fetcher SHALL send 0 capture requests and THE Exhume_CLI SHALL report `downloaded` as 0 for every Host.
5. WHEN the conditions of Requirement 22.4 hold, THE Evidence_Store SHALL write no capture file and leave `index.json` byte-identical.
6. WHEN a run is terminated at any point, THE Evidence_Store SHALL leave `index.json` either absent, if it was never written, or as a valid Index containing every entry whose rewrite under Requirement 21.5 completed, so that the next run counts those Captures as cached.
7. IF a run is terminated after a capture file was written but before its Index rewrite completed, THEN THE Capture_Fetcher SHALL treat the Capture as not cached in the next run and fetch the Capture again when it is selected.

### Requirement 23: Test isolation

**User Story:** As the Revenant developer, I want the test suite to run without network access, so that tests are fast, repeatable and never load the Archive.

#### Acceptance Criteria

1. THE Exhume test suite SHALL give the Archive_Client, in every non-live test, an httpx client built on `httpx.MockTransport`, so that no request leaves the test process.
2. THE Exhume test suite SHALL provide fixtures for the observed facts F1 to F8 and F10 that match the status, the quoted headers and the shown body rows or prefix, and the F5 fixture SHALL be the full body captured once by the live smoke test or a one-off fetch and committed under `tests/exhume/fixtures/`, with a test asserting a length of 15479 bytes and the F8 digest `M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY`.
3. THE Exhume test suite SHALL build Offline page fixtures only from F9 (title "Internet Archive: Temporarily Offline"), served with status 200 and with at least one non-2xx status, and SHALL invent no other Archive behaviour.
4. THE Exhume test suite SHALL use a fake Clock in every non-live test that touches the Archive_Client, the Rate_Limiter or the Retry_Policy, where the fake Clock's sleep function advances monotonic time without real waiting and records the requested durations.
5. THE Exhume test suite SHALL use a fresh temporary Evidence_Root for every non-live test that writes evidence, so that no non-live test touches `./evidence`.
6. THE Exhume test suite SHALL include exactly one test marked `@pytest.mark.live`, which is deselected by default through `addopts`, selected by `pytest -m live`, sends real requests to the Archive and verifies Requirements 24.1 to 24.4 and 24.7.
7. THE Exhume test suite SHALL implement each of the correctness properties P1 to P16 as at least one Hypothesis test that names its property id in the test name or docstring.

### Requirement 24: Definition of done

**User Story:** As the hackathon entrant, I want an end-to-end check against the real Archive, so that I know Exhume produces the evidence the demo needs.

#### Acceptance Criteria

1. WHEN `revenant exhume yahoo-finance-ichart --max-captures 20` runs against the real Archive from the repository root with the default Evidence_Root, THE Exhume_CLI SHALL end the run with 20 selected Data captures for the Host `ichart.yahoo.com`, each a Cached capture with kind `data` at the end of the run, with `downloaded` plus `cached` equal to 20 in that Host's row and no shortfall indicator.
2. WHEN the run of Requirement 24.1 finishes, THE Evidence_Store SHALL hold Index entries for those 20 Data captures that cover at least 2 distinct Intervals other than `none` and at least 3 distinct capture years (first four digits of `requested_timestamp`).
3. WHEN the run of Requirement 24.1 finishes, THE Evidence_Store SHALL have written `evidence/yahoo-finance-ichart/index.json`, which parses with the Index model (Requirement 21.1) and contains the entries of those 20 Data captures.
4. WHEN the same command runs a second time directly after, with the same Evidence_Root and without `--refresh`, THE Capture_Fetcher SHALL download 0 Captures, so that `downloaded` is 0 in every Host row.
5. THE live smoke test (Requirement 23.6) SHALL verify Requirements 24.1 to 24.4 and 24.7, and SHALL run only with `-m live`.
6. WHEN `pytest` runs with no extra options, THE Exhume test suite SHALL deselect the live test and finish with zero failures and zero errors and exit code 0.
7. WHEN the run of Requirement 24.1 finishes, THE Exhume_CLI SHALL exit with exit code 0 under Requirement 4.9.

## Correctness Properties

These properties are written for Hypothesis. Each one names the requirements it checks. All
of them run without network access, using `httpx.MockTransport` and a fake Clock where I/O
is involved.

- **P1 CDX row round-trip** (Req 7.7, 7.8): for any list of valid CDX rows and any
  permutation of the `fl` header fields, printing with the CDX_Printer and parsing with the
  CDX_Parser returns the same rows.
- **P2 CDX pagination** (Req 6.4, 6.5, 7.2, 7.3): for any list of rows and optional
  Resume_Key, the CDX_Parser returns exactly those rows and that key; for any split of a
  listing into pages chained by Resume_Keys, the CDX_Client served by MockTransport returns
  a listing equal to the unpaginated listing.
- **P3 Offline detector** (Req 17): for any generated valid CSV, JSON or XML body, the
  Offline_Detector returns false; for the Offline page with any status code, any leading
  whitespace or BOM, and any letter-case variation of the `<!DOCTYPE`, `<html>` and
  `<title>` tags, the Offline_Detector returns true.
- **P4 Path safety** (Req 2.13, 20.1, 20.3 to 20.5): for any valid (Host, Requested
  timestamp, Digest) triples, the computed paths use the lowercased Host, are pairwise
  distinct for distinct triples and resolve inside the Evidence_Root; for any arbitrary host or `original` strings (including `..`, `/`,
  `\`, `%2e%2e`, drive letters), either validation rejects the value or the resolved path
  stays inside the Evidence_Root.
- **P5 Rate limiter** (Req 15): for any sequence of request outcomes (success, retryable
  failure, redirect) under a fake Clock, no two request start times differ by less than
  1 second.
- **P6 Backoff** (Req 16): for any sequence of retryable failures with optional
  `Retry-After` values, the waits are non-decreasing when no `Retry-After` is given, the
  first wait is 2 s, every wait is at most 60 s, every wait is at least min(60, R), and no
  request makes more than 5 attempts.
- **P7 Selection** (Req 11): for any listing and N, selection on any permutation of the
  listing returns the same set; the result has min(N, E) items and no duplicate Digest; and
  when N is at least the number of non-empty Strata, every non-empty Stratum is covered.
- **P8 Backfill** (Req 12, 12.10): for any listing, N and set of Captures that fail, the
  Capture_Fetcher makes at most 2×N Download attempts per Host and selects no Capture twice
  in a run, and repeated runs with the same inputs produce the same sequence of selections
  and replacements.
- **P9 Dedup** (Req 8.2, 8.3): for any listing with repeated Digests, deduplication keeps exactly
  one row per Digest, and that row has the earliest timestamp of its Digest.
- **P10 Auth filter** (Req 13, 13.2): for any URL that contains a parameter whose name
  contains an auth-like substring in any letter case, including percent-encoded names such
  as `%63rumb` and the accepted false positive `keyword`, the Ethics_Filter rejects it; for any URL whose
  parameter names contain none of the substrings, the Ethics_Filter accepts it.
- **P11 Idempotence** (Req 22.4, 22.5): for any mocked Archive with successful responses, running
  Exhume twice downloads 0 Captures on the second run and leaves `index.json`
  byte-identical.
- **P12 Index round-trip** (Req 21.7): for any valid Index object, serialize then parse
  produces an equal object, and serialize is deterministic.
- **P13 Digest known pair** (Req 19.1 to 19.3): the digest function maps the F5 body fixture
  to `M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY`; for any bytes, the output is 32 characters of
  `A-Z2-7`.
- **P14 Shape invariance** (Req 10.5, 10.6): for any query string, the Parameter shape,
  Interval and `s` value are unchanged by reordering the parameters and by percent-encoding
  the value of `s`.
- **P15 Served timestamp** (Req 14.3, 14.4): for any 14-digit timestamp and `original` URL,
  extracting the Served timestamp from a final URL of the form in F6 returns that
  timestamp; for any UTC datetime, formatting it as a `Memento-Datetime` header and
  extracting returns the same 14-digit timestamp.
- **P16 Response classifier** (Req 14.5 to 14.8, 16.1, 16.5 to 16.7): for any capture kind
  (data or error), CDX `statuscode`, final status code and presence or absence of a
  Memento-Datetime header, with a body that is not an Offline page, the classifier returns
  exactly one of accept, retry or permanent reject, and: an Error capture whose status
  equals the CDX `statuscode` with a Memento-Datetime header is accepted; any other 4xx
  except 429 is a permanent reject for both kinds, including a 4xx Error capture response
  without a Memento-Datetime header; a Data capture with a 4xx other than 429 is a
  permanent reject whether or not the header is present; and 429 or 5xx without an
  accepting match is retried.

## Non-goals

- Scanning old client source code for request patterns.
- Contract inference, which belongs to the Autopsy stage.
- Any user interface beyond the Run_Summary.
- Reading victim run logs (`victims/<client>/evidence/*.json`, field `urls_called`) as
  client-request evidence. `structure.md` assigns this to Exhume; it is deferred to a later
  spec.
- Discovery of documentation pages. `product.md` mentions docs pages; they are deferred to
  a later spec.
- Scanning capture bodies for personal data. Only `original` URLs are filtered
  (Requirement 13).
- Concurrent or asynchronous downloads.

## Appendix A: Verified Archive behaviour

Facts F1 to F8 and F10 were observed on 2026-11-15 with the User-Agent
`Revenant/0.1 (+https://github.com/Manthan-1610/revenant)` and at least 1 second between
requests. Fact F9 is user-provided or taken from steering files and was not re-observed.

### F1: CDX data page 1 (collapse, fl, filters, pagination)

Query:
`https://web.archive.org/cdx/search/cdx?url=ichart.yahoo.com/table.csv*&output=json&collapse=digest&filter=statuscode:200&filter=mimetype:text/csv&fl=timestamp,original,mimetype,statuscode,digest,length&limit=3&showResumeKey=true`

Response: HTTP 200, Content-Type `application/json`. Excerpt:

```
[["timestamp","original","mimetype","statuscode","digest","length"],
["20131213174436","http://ichart.yahoo.com:80/table.csv?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv","text/csv","200","M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY","6731"],
["20090103230517","http://ichart.yahoo.com:80/table.csv?s=0298.HK&d=0&e=1&f=2009&g=d&a=0&b=1&c=2003&ignore=.csv","text/csv","200","F7M7VBDFW7UHBCUJX3VCU3EN54CCVDOU","14808"],
["20090129101731","http://ichart.yahoo.com:80/table.csv?s=0005.HK&a=0&b=1&c=2003&d=0&e=20&f=2009&g=d&ignore=.csv","text/csv","200","IHBKV5JJ7OXMYBPR2BZY25W2Q6GNQSBG","22849"],
[],
["eJwVyk0KgCAQQOGrtBoIwmYMIRdDZ1EzlX4Ek6Dbl8uP91w-h9fEnIfkoim1H6uxhxfufhbDCJYJHEvECdafniXB1qwh8AopXLl4bjvcjIhKxL1rGUlqmpVU9AEE9hxp"]]
```

Observations: the header row comes first; `original` contains `:80`; rows are not in
timestamp order; parameter order varies; the CDX `length` (6731) is the compressed archive
record length, not the body size (F8: the body is 15479 bytes).

### F2: CDX data page 2 with resumeKey

Query: the F1 query plus `&resumeKey=<url-encoded key from F1>`.

Response: HTTP 200. Excerpt:

```
[["timestamp","original","mimetype","statuscode","digest","length"],
["20090202003604","http://ichart.yahoo.com:80/table.csv?s=0921.HK&a=0&b=1&c=2003&d=0&e=21&f=2009&g=d&ignore=.csv","text/csv","200","IVEFWI4ZNPMWXQOB7U7MQCBKDTPDSNPN","11134"],
...
[],
["eJwVylsKgCAQQNGt9DUQSI2PpD6G1mJmKT2ElKDdp5-He2282Gd8jCxYb57c9tksp-tsemdDCAtxsCQQJayFjsQAWzHnsNMKYb_j46jukAinUXf-aGpGgYproeT0AwWDHG4"]]
```

Observations: each page repeats the header row; page 2 does not overlap page 1; pagination
continues through a new key; the resume key follows an empty `[]` row.

### F3: The last page has no resume key

Query:
`https://web.archive.org/cdx/search/cdx?url=ichart.yahoo.com/table.csv*&output=json&collapse=digest&filter=statuscode:4..&fl=timestamp,statuscode,digest&limit=1000&showResumeKey=true`

Response: HTTP 200, 230 array elements (header plus 229 rows). The final elements are data
rows, with no `[]` row and no key:

```
...
["20170615233615","404","4A74BVJONEBEI3G6JYPZNCAJ3KMVUOW6"],
["20110106053548","404","HEERRGOKPBZAYTDVBK2NA4BPKFRTFE5G"],
["20121211081143","404","N26ZVLVE3ELLXVEX5R3ZPEKPT3WR6OOB"]]
```

### F4: 4xx discovery works with a regex status filter

Query:
`https://web.archive.org/cdx/search/cdx?url=ichart.yahoo.com/table.csv*&output=json&collapse=digest&filter=statuscode:4..&fl=timestamp,original,mimetype,statuscode,digest,length&limit=5&showResumeKey=true`

Excerpt:

```
[["timestamp","original","mimetype","statuscode","digest","length"],
["20040609203020","http://ichart.yahoo.com:80/table.csv","text/html","404","SL7KPZOPYQFYEVOT2GXE37BDFGTW7763","801"],
["20040611173420","http://ichart.yahoo.com:80/table.csv","text/html","404","LYQV5D4ZT67A4ZP75HS5X7PKXON4ZPWS","801"],
...
[],
["eJxLzs_VqUzMyM_XyUzOSCwq0dQvSUzKSdVLLi5TMDIwMDEwM7Q0MjQ0NjUAADqODO8"]]
```

Observation: 4xx captures are `text/html`, and many are near-identical 404 pages with
different digests of about 800 bytes.

### F5: Raw id_ fetch of an exact timestamp

Query:
`https://web.archive.org/web/20131213174436id_/http://ichart.yahoo.com:80/table.csv?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv`

Response: HTTP 200, no redirect. Headers excerpt:

```
Content-Type: text/csv
memento-datetime: Fri, 13 Dec 2013 17:44:36 GMT
x-archive-orig-date: Fri, 13 Dec 2013 17:44:36 GMT
x-archive-src: alexa20131214-14/52_37_20131213174423_crawl100_IndexOnly.arc.gz
```

The body (15479 bytes) begins:

```
Date,Open,High,Low,Close,Volume,Adj Close
2010-01-25,546.59,549.88,525.61,529.94,4021800,529.94
2010-01-19,581.20,590.42,534.86,550.01,5168800,550.01
```

Observation: weekly `g=w` rows, newest first.

### F6: A non-exact timestamp redirects to the nearest capture

Query (redirects not followed):
`https://web.archive.org/web/20131213000000id_/http://ichart.yahoo.com:80/table.csv?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv`

Response:

```
HTTP/1.1 302 FOUND
location: https://web.archive.org/web/20131213174436id_/http://ichart.yahoo.com/table.csv?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv
```

Observation: the served timestamp is in the redirect target path; the target URL drops
`:80`.

### F7: Memento-Datetime gives the served time

From the F5 response: `memento-datetime: Fri, 13 Dec 2013 17:44:36 GMT`.

### F8: CDX digest equals base32(SHA-1(raw body))

The F5 body saved to disk is 15479 bytes. Its base32(SHA-1) is
`M37VRFD74CQFJ6RCU52MNGMWIP5YDNFY`, equal to the CDX digest of the same capture in F1.

### F9: User-provided and steering-sourced facts (not re-observed on 2026-11-15)

- Under load, the Archive returns an HTML page titled "Internet Archive: Temporarily
  Offline", sometimes with HTTP 200 (user-provided; `tech.md`).
- ichart.yahoo.com has 14,651 unique `200 text/csv` captures (2004–2017,
  `collapse=digest`), too many for one unpaginated request; ichart.finance.yahoo.com has
  22,209 (`product.md`).
- Captures include `g=d` and `g=w`; ichart.finance.yahoo.com also has `g=m` and the
  undocumented `g=v` (`product.md`).
- Captured requests include ones with only `s` and ones with empty `a`–`g` values; symbols
  arrive raw (`s=^DJI`) and percent-encoded (`s=%5EAEX`) (`product.md`).
- The original hosts no longer resolve in DNS. The victim run log
  `victims/ystockquote/evidence/2026-11-15T214211Z-dead.json` records
  `URLError: <urlopen error [Errno 11001] getaddrinfo failed>` for a call to
  `http://ichart.yahoo.com/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv`.

### F10: Replay of an archived 404 carries the archived status and Memento-Datetime

Query (redirects followed), a 404 capture listed in F4:
`https://web.archive.org/web/20040609203020id_/http://ichart.yahoo.com:80/table.csv`

Response:

```
HTTP/1.1 404 Not Found
Content-Type: text/html; charset=iso-8859-1
memento-datetime: Wed, 09 Jun 2004 20:30:20 GMT
```

The body begins:

```
<html><head><title>Yahoo! -
404 Not Found</title></head><body><center><table
```

Observation: the Archive replays an archived 4xx with the archived status code and a
`Memento-Datetime` header. The HTTP status alone cannot tell a replayed archived 404 apart
from the Archive's own "not archived" 404; the Memento-Datetime header can.
