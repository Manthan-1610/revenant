# Requirements Document

## Introduction

Exhume is the first of Revenant's five stages. Given the slug of a dead API, Exhume reads the
Tombstone `tombstones/<slug>.toml`, lists archived captures of every Host through the Wayback
Machine CDX API, downloads a small deterministic sample of raw captures and stores them under
`evidence/<slug>/` with an Index. The Autopsy stage reads this evidence later.

This is the MVP scope for a 1.5 to 2 day build. It also covers the project scaffold, because
Exhume is the first code in the repository. Exhume follows `tech.md`, `necromancy-ethics.md`
and `structure.md`. References F1 to F22 point to the observed Archive facts in Appendix A.

## Glossary

- **Revenant**: the product and its Python package `revenant/`.
- **Exhume**: the stage specified here, in the package `revenant/exhume/`.
- **Scaffold**: the packaging, package skeleton, test layout and first Tombstone.
- **Exhume_CLI**: the `revenant exhume` command of the `revenant` console script.
- **Archive**: the Internet Archive Wayback Machine at `https://web.archive.org`.
- **Archive_Client**: sends every Archive request, applying User-Agent, Rate_Limiter and
  Retry_Policy.
- **Rate_Limiter**: spaces the start times of Archive requests.
- **Retry_Policy**: decides whether a failed Archive request is retried and how long to wait.
- **Clock**: injected source of monotonic time, UTC time and a sleep function; tests use a fake.
- **Config**: the Revenant configuration source that supplies the User-Agent.
- **Tombstone**: the TOML manifest `tombstones/<slug>.toml` describing one dead API.
- **Tombstone_Loader**: reads and validates a Tombstone.
- **Slug**: identifier of a dead API, for example `yahoo-finance-ichart`.
- **Host**: one hostname from the Tombstone's `hosts` field, lowercased.
- **CDX_Client**: builds CDX queries, pages through the results and deduplicates them.
- **CDX_Parser**: parses one CDX JSON page into CDX rows and an optional Resume_Key.
- **CDX row**: a record with `timestamp`, `original`, `mimetype`, `statuscode`, `digest`, `length`.
- **Resume_Key**: pagination token sent as a one-string row after an empty row `[]` (F1, F2).
- **Listing**: the complete, deduplicated CDX rows of one Host and one pass (data or error).
- **Data capture**: a capture from the data pass (status 2xx, a Tombstone mimetype).
- **Error capture**: a capture from the error pass (status 4xx), stored with `kind="error"`.
- **Error page**: a Data capture whose body is non-Offline HTML while its CDX mimetype is not
  `text/html`.
- **Error_Evidence**: stored captures of kind `error` or `error_page`; at most 10 per Slug.
- **Offline page**: the Archive's HTML page titled "Internet Archive: Temporarily Offline" (F9).
- **Offline_Detector**: decides whether a response is an Offline page.
- **Content_Validator**: classifies a fetched body and checks its digest.
- **Query_Parser**: parses the query string of a CDX `original` URL into decoded name-value pairs.
- **Parameter shape**: `s_only` (only `s`, optionally `ignore`), `empty_range` (all of `a` to `g`
  present and empty), `full_range` (all of `a` to `g` present and non-empty), else `other`.
- **Interval**: the value of the `g` parameter, or `none` when absent or empty.
- **Candidate**: a row of a Host's data Listing that passes the Ethics_Filter.
- **Group**: the Candidates of one Host that share one (Interval, Parameter shape) pair.
- **Selector**: chooses which Candidates of a Host to download.
- **N**: the maximum number of Data captures stored per Host (`--max-captures`, default 50).
- **Ethics_Filter**: drops rows whose `original` URL has an Auth-like parameter.
- **Auth-like parameter**: a parameter whose name contains `crumb`, `cookie`, `token`, `key`,
  `session` or `email`, compared case-insensitively.
- **Capture_Fetcher**: downloads raw captures.
- **Substituted capture**: a stored-candidate response whose `served_timestamp` is not null, differs from `requested_timestamp`, and whose computed digest does not equal the CDX digest (F14).
- **Evidence_Root**: the directory from `--evidence-dir`, default `./evidence`.
- **Evidence_Store**: writes capture files, Listings and the Index below the Evidence_Root.
- **Index**: `<Evidence_Root>/<slug>/index.json`, listing every capture stored for the Slug.
- **Cached capture**: a capture whose Index entry exists and whose file has the recorded size.
- **Atomic write**: write a temp file in the destination directory, then rename it over the target.
- **Run_Summary**: the Rich table printed at the end of a run.

## Requirements

### Requirement 1: Project scaffold

**User Story:** As the Revenant developer, I want a working package and test setup, so that every stage has a home and tests run with one command.

#### Acceptance Criteria

1. THE Scaffold SHALL provide a root `pyproject.toml` with the hatchling build backend, `requires-python = ">=3.12"`, runtime dependencies httpx, pydantic 2, typer and rich, and an optional `dev` group with pytest, hypothesis and ruff.
2. THE Scaffold SHALL declare the console script `revenant` pointing to `revenant.cli:main`, so that after `pip install -e ".[dev]"` the command `revenant --help` exits 0 and lists `exhume`.
3. THE Scaffold SHALL create `revenant/__init__.py` and the subpackages `exhume`, `autopsy`, `reanimate`, `pulse`, `haunt` and `api`, each with an `__init__.py`, with Exhume code only in `revenant/exhume/` and `revenant/cli.py`.
4. THE Scaffold SHALL create `tests/exhume/` and configure pytest with `addopts = "-m 'not live'"` and a registered `live` marker, so that `pytest` with no arguments runs only non-live tests and exits 0.
5. THE Scaffold SHALL create `tombstones/yahoo-finance-ichart.toml` with the six fields of `structure.md`: `slug = "yahoo-finance-ichart"`, `name = "Yahoo Finance historical prices"`, `died = "2017-05"`, `hosts = ["ichart.yahoo.com", "ichart.finance.yahoo.com", "real-chart.finance.yahoo.com"]`, `paths = ["table.csv"]`, `mimetypes = ["text/csv"]`.
6. THE Scaffold SHALL keep `.gitignore` free of patterns that ignore `.kiro/`, `evidence/<slug>/index.json` or capture files, and SHALL ignore `evidence/*/cdx/` (stored Listings are a regenerable cache of several MB per host).

### Requirement 2: Tombstone loading

**User Story:** As a user, I want the manifest validated, so that a typo fails fast instead of sending wrong requests to the Archive.

#### Acceptance Criteria

1. WHEN the Exhume_CLI receives a Slug, THE Tombstone_Loader SHALL read `tombstones/<slug>.toml` relative to the current working directory and validate the file with a Pydantic model with the fields `slug`, `name`, `died`, `hosts`, `paths` and `mimetypes`.
2. THE Tombstone_Loader SHALL require all six fields, with `hosts`, `paths` and `mimetypes` as non-empty lists of strings, and SHALL reject any other top-level field.
3. THE Tombstone_Loader SHALL lowercase every Host.
4. IF the `slug` field differs from the Slug in the file name, THEN THE Tombstone_Loader SHALL fail validation with an error that names both values.
5. IF the Tombstone file is missing, is not valid TOML or fails validation, THEN THE Exhume_CLI SHALL print an error that names the file and any failing fields, exit with a non-zero code and send no Archive request.

### Requirement 3: CDX discovery

**User Story:** As the Autopsy stage, I want every unique archived response of each Host listed, so that the sample can draw on the whole history of the API.

#### Acceptance Criteria

1. WHEN discovering Data captures, THE CDX_Client SHALL, for each Host and each Tombstone path in order, send a GET to `https://web.archive.org/cdx/search/cdx` with `url=<host>/<path>*`, `output=json`, `collapse=digest`, `fl=timestamp,original,mimetype,statuscode,digest,length`, `filter=statuscode:2..`, one `filter=mimetype:` regex matching exactly the Tombstone mimetypes, `limit=<page size of at most 1000>` and `showResumeKey=true` (F1).
2. WHEN a CDX page arrives, THE CDX_Parser SHALL map each data row by header field name and return a final one-string row that follows a `[]` row as the Resume_Key, excluded from the rows, or no Resume_Key when that pair is absent (F1 to F3).
3. WHEN a page yields a Resume_Key, THE CDX_Client SHALL request the next page with the same parameters plus `resumeKey=<key>`, stopping at the first page without a Resume_Key (F2, F3).
4. WHEN every path of a Host and pass is complete, THE CDX_Client SHALL merge the rows into one Listing with one row per digest, keeping the earliest timestamp, and THE Evidence_Store SHALL write the Listing with an Atomic write to `<Evidence_Root>/<slug>/cdx/<host>.json` (data) or `<host>.errors.json` (error).
5. IF a CDX request fails after the Retry_Policy stops or a page cannot be parsed, THEN THE CDX_Client SHALL mark discovery for that Host and pass as failed, write no partial Listing and continue with the next Host.
6. WHEN the data downloads of all Hosts are done, THE CDX_Client SHALL run an error pass with the parameters of 3.1 but `filter=statuscode:4..` and no mimetype filter (F3, F4), cached as in 3.4, from which THE Capture_Fetcher SHALL fetch Error captures round-robin over Hosts in Tombstone order, each Host in (timestamp, digest) order, accepting a replay only when its status equals the CDX status and a `Memento-Datetime` header is present (F10), rejecting it without retry otherwise, until 10 Error_Evidence items exist for the Slug.

### Requirement 4: Selection

**User Story:** As the Autopsy stage, I want a small sample that spans intervals and request shapes, so that contract inference sees every variant of the API.

#### Acceptance Criteria

1. THE Query_Parser SHALL HTML-unescape the query string of an `original` URL (`html.unescape`) and parse the result, including URLs with `:80` and any parameter order, into percent-decoded name-value pairs, so that `s=^DJI` and `s=%5EDJI` give the same `s` value, `s=DISH&amp` yields `s=DISH` and `&amp;g=d` yields `g=d`, while fetching uses `original` unchanged (F1, F9, F15).
2. THE Selector SHALL place each Candidate of a Host in the Group of its (Interval, Parameter shape) and order the Candidates of each Group by (timestamp, digest).
3. THE Selector SHALL allocate picks round-robin across Groups in sorted (Interval, Parameter shape) order, and for a Group of m Candidates given k picks SHALL take the Candidates at indices floor(i × m / k) for i = 0 to k − 1, using no random number generator.
4. THE Selector SHALL select at most N Candidates per Host, at most one per digest, and at least one from every Group when N is at least the number of Groups.
5. THE Selector SHALL return the same selection for the same Candidate set and N, whatever the order of the Listing rows.
6. THE Selector SHALL define the backfill order of a Host as its unselected Candidates taken round-robin across Groups in sorted Group order, each Group in (timestamp, digest) order.

### Requirement 5: Raw capture download

**User Story:** As the Autopsy stage, I want the original response bytes exactly as archived, so that contract inference sees the dead API and not the Archive's wrapper.

#### Acceptance Criteria

1. WHEN fetching a capture, THE Capture_Fetcher SHALL send a GET through the Archive_Client to `https://web.archive.org/web/<timestamp>id_/<original>`, with `<original>` copied unchanged including any `:80` and redirects followed (F5, F6).
2. WHEN a capture is stored, THE Capture_Fetcher SHALL record `requested_timestamp` (the CDX timestamp) and `served_timestamp`, taken from the 14 digits after `/web/` in the final URL path, else from the `Memento-Datetime` header converted to UTC `YYYYMMDDhhmmss`, else null (F6, F7).
3. THE Capture_Fetcher SHALL pass the body to the Content_Validator and the Evidence_Store byte for byte, without charset decoding, newline conversion or trimming.
4. IF a Data capture's final response has a 4xx status other than 429, THEN THE Capture_Fetcher SHALL reject the capture without retry.
5. IF a Data capture is rejected, exhausts its retries or is classified as an Error page, THEN THE Capture_Fetcher SHALL fetch the next Candidate in backfill order (Requirement 4.6) until N Data captures of kind `data` are stored for the Host or no Candidate remains.
6. IF a Data capture's response is a Substituted capture, THEN THE Capture_Fetcher SHALL re-fetch the capture once through the Archive_Client, and IF the second response is also a Substituted capture, THEN THE Capture_Fetcher SHALL reject the capture, store nothing and count the capture as rejected (F14).

### Requirement 6: Politeness

**User Story:** As a respectful Archive client, I want requests spaced, identified and backed off, so that Revenant never adds load spikes to the Archive.

#### Acceptance Criteria

1. THE Rate_Limiter SHALL keep at least 1 second of Clock monotonic time between the starts of any two Archive requests in a run, shared across CDX requests, capture requests, retries and redirect hops of all Hosts, waiting only through the Clock's sleep function.
2. WHEN an attempt ends with a connection error, a timeout, status 429, a 5xx status or an Offline page, THE Retry_Policy SHALL retry the request, making at most 5 attempts in total.
3. WHEN retrying after attempt k, THE Retry_Policy SHALL wait min(60, max(2 × 2^(k−1), R)) seconds, where R is the `Retry-After` value (integer seconds or HTTP date) or 0 when the header is absent or unparseable.
4. IF a CDX request or a Data capture request receives a 4xx status other than 429, THEN THE Retry_Policy SHALL make no further attempt.
5. THE Archive_Client SHALL send exactly one `User-Agent` header on every request, set to the Config value, which defaults to `Revenant/0.1 (+https://github.com/Manthan-1610/revenant)`.
6. THE Archive_Client SHALL take the httpx client and the Clock as injected dependencies and send requests one at a time.

### Requirement 7: Content checks

**User Story:** As the Autopsy stage, I want Archive outage pages and HTML error pages kept out of the data, so that contract inference never mistakes them for API responses.

#### Acceptance Criteria

1. THE Offline_Detector SHALL classify a response as an Offline page only when the response is HTML (Content-Type media type `text/html`, or a body starting with `<!DOCTYPE` or `<html` case-insensitively after an optional UTF-8 BOM and whitespace) and its first `<title>` text contains `Temporarily Offline` (F9).
2. THE Offline_Detector SHALL give the same classification for every HTTP status code, including 200 (F9).
3. WHEN the Offline_Detector classifies a response as an Offline page, THE Evidence_Store SHALL store nothing from the response, and THE Retry_Policy SHALL retry the request under Requirement 6.2.
4. WHEN a Data capture body is HTML and not an Offline page while its CDX mimetype is not `text/html`, THE Content_Validator SHALL classify the body as an Error page.
5. WHEN an Error page is classified, THE Evidence_Store SHALL store the Error page with `kind="error_page"` and extension `html` if fewer than 10 Error_Evidence items exist for the Slug, and SHALL discard the body as rejected otherwise.
6. THE Content_Validator SHALL set `digest_verified` to whether the unpadded upper-case base32 SHA-1 of the stored bytes equals the CDX digest (F8), and SHALL store a capture whose digest mismatches with `digest_verified=false` when its `served_timestamp` is null or equals its `requested_timestamp` (Substituted captures follow Requirement 5.6).

### Requirement 8: Ethics filter

**User Story:** As the project owner, I want captures of authenticated requests excluded, so that Revenant never stores credentials or personal data found in archived URLs.

#### Acceptance Criteria

1. IF a Listing row's `original` URL has an Auth-like parameter, THEN THE Ethics_Filter SHALL drop the row before selection, in both the data pass and the error pass.
2. THE Ethics_Filter SHALL match only percent-decoded parameter names by case-insensitive substring, including names without a value, so that `apiKey=x`, `X-Crumb=1`, `%63rumb=1` and the accepted false positive `keyword=x` are dropped.
3. THE Ethics_Filter SHALL accept a URL whose Auth-like substrings appear only in parameter values, the path or the fragment, so that `s=TOKEN` is accepted.
4. WHEN the Ethics_Filter drops a row, THE Capture_Fetcher SHALL send no request for the row, and THE Evidence_Store SHALL write the row's URL to no file, including stored Listings and the Index.
5. THE Evidence_Store SHALL store in each Listing file the count of dropped rows, so that THE Exhume_CLI counts dropped rows as rejected for cached and fresh Listings alike.

### Requirement 9: Evidence store and idempotence

**User Story:** As the Autopsy stage, I want captures at predictable paths with one index, so that I can load evidence with its provenance and reruns skip finished work.

#### Acceptance Criteria

1. THE Evidence_Store SHALL store each capture with an Atomic write at `<Evidence_Root>/<slug>/<host>/<timestamp>-<digest>.<ext>`, where `<ext>` is `csv` for `text/csv`, `xml` for `text/xml` or `application/xml`, `json` for `application/json`, `html` for `text/html` and Error pages, and `bin` otherwise.
2. THE Evidence_Store SHALL keep one Index per Slug, a Pydantic model whose entries are keyed `<host>/<timestamp>-<digest>` and hold `host`, `kind` (`data`, `error` or `error_page`), `requested_timestamp`, `served_timestamp`, `original`, `mimetype`, `statuscode`, `digest`, `length`, `final_url`, `path`, `size`, `sha256`, `content_type`, `digest_verified` and `fetched_at`.
3. WHEN a capture is stored, THE Evidence_Store SHALL rewrite the Index with an Atomic write before the next download starts, with sorted keys and fixed indentation so that equal contents give identical bytes.
4. WHEN a selected capture is a Cached capture, THE Capture_Fetcher SHALL send no request for the capture, and THE Exhume_CLI SHALL count the capture as cached.
5. WHILE `--refresh` is not given, WHEN a stored Listing exists for a Host and pass, THE CDX_Client SHALL reuse the stored Listing and send no CDX request for that Host and pass.
6. WHEN Exhume runs a second time with the same Tombstone, arguments and stored Listings after a run without failures, THE Capture_Fetcher SHALL download 0 captures and THE Evidence_Store SHALL leave `index.json` byte-identical.

### Requirement 10: CLI, summary and definition of done

**User Story:** As the hackathon entrant, I want one command with a per-host summary that works against the real Archive, so that I can see what Exhume did and know the demo evidence exists.

#### Acceptance Criteria

1. THE Exhume_CLI SHALL accept `revenant exhume <slug> [--max-captures N] [--evidence-dir PATH] [--refresh]`, with N an integer of at least 1 defaulting to 50 and PATH defaulting to `./evidence`, leaving argument validation to Typer.
2. WHEN a run finishes, THE Exhume_CLI SHALL print a Run_Summary with one row per Host in Tombstone order and the columns `found`, `downloaded`, `cached` and `rejected`, followed by a line with the Slug's Error_Evidence count.
3. THE Exhume_CLI SHALL report `found` as the number of data Listing rows including Ethics_Filter drops, and `rejected` as the Host's Ethics_Filter drops plus its rejected captures.
4. IF CDX discovery failed for at least one Host and pass, THEN THE Exhume_CLI SHALL name each failed Host and pass after the Run_Summary and exit with a non-zero code, and every other run SHALL exit 0.
5. WHEN `revenant exhume yahoo-finance-ichart --max-captures 20` runs against the real Archive, THE Exhume_CLI SHALL store 20 Data captures for `ichart.yahoo.com` covering at least 2 distinct `g` values and at least 3 distinct capture years, write `evidence/yahoo-finance-ichart/index.json` and exit 0.
6. WHEN the command of Requirement 10.5 runs a second time with the same Evidence_Root, THE Exhume_CLI SHALL report `downloaded` as 0 for every Host, as checked by the single `@pytest.mark.live` smoke test together with Requirement 10.5.

## Correctness Properties

Each property is a Hypothesis test that names its id. Non-live tests use `httpx.MockTransport`,
a fake Clock whose sleep advances time without waiting, and a temporary Evidence_Root.

- **P1 CDX page parse** (Req 3.2): headers in any field order map rows by name; a trailing `[]`
  plus one-string row is returned as the Resume_Key and excluded from the rows; no key when
  absent (F1 to F3).
- **P2 Offline detector** (Req 7.1, 7.2): no valid CSV, JSON or XML body with a non-`text/html`
  Content-Type is an Offline page; the F9 page is detected with any status code.
- **P3 Selection** (Req 4.3 to 4.5): the same Candidate set in any order gives the same
  selection, with at most N items and unique digests.
- **P4 Rate limiter** (Req 6.1): under a fake Clock, no two request starts are less than 1 s
  apart, including retries and redirect hops.
- **P5 Auth filter** (Req 8.2, 8.3): parameter names are matched and values are not, so
  `s=TOKEN` is accepted and `apiKey=x` is rejected.

## Non-goals (not Exhume's job, or not this spec)

- Scanning old client source code for request patterns.
- Contract inference, which belongs to the Autopsy stage.
- Any user interface beyond the Run_Summary.
- Reading victim run logs (`victims/<client>/evidence/*.json`, field `urls_called`).
- Discovery of documentation pages.
- Scanning capture bodies for personal data.
- Concurrent or asynchronous downloads.

## Deferred (post-hackathon)

- `--mimetype` option overriding the Tombstone mimetypes.
- CDX_Printer and the print-then-parse round-trip property.
- Selection guarantee ladder (Interval, shape and year thresholds) and year stratification.
- Separate data and error backfill limits, the 2×N attempt cap and the 20 error-attempt cap.
- Permanent-rejection records in the Index and their exclusion from later runs.
- Halting with an error on a corrupt or invalid `index.json`.
- User-Agent validation (email addresses, control characters, empty values).
- CLI edge-case validation beyond Typer (empty values, evidence dir that is a file).
- Slug, hostname and path grammar checks and duplicate-Host detection in the Tombstone.
- Multi-path handling beyond a simple loop; stored-Listing query-parameter matching.
- Precedence rules between filters (unparseable URLs, invalid CDX rows, Ethics_Filter).
- CDX row format validation (timestamp, digest) and strict parse-error reporting by row index.
- Repeated-Resume_Key guard.
- Path-traversal checks beyond the fixed layout.
- Per-request timeout and redirect-hop limits.
- Detailed Error capture rules (archived 429 replays, status mismatch edge cases).
- Exact Run_Summary accounting (one column per capture, shortfall indicator, error column).
- Interrupted-run guarantees beyond atomic writes.
- Rate_Limiter sleep-call rules (single sleep, no sleep before the first request).
- Other properties: Index round-trip, dedup, backoff sequence, idempotence, digest known pair,
  query-shape invariance, path uniqueness, response classifier, backfill.

## Appendix A: Verified Archive behaviour

Facts F1 to F8 and F10 were observed on 2026-11-15 with the User-Agent
`Revenant/0.1 (+https://github.com/Manthan-1610/revenant)` and at least 1 second between
requests. Facts F11 and F12 were observed by the user on 2026-11-15 with the User-Agent
`Revenant/0.1 (test)`, one request each. Fact F9 is user-provided or taken from steering files and was not
re-observed.

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

Response: HTTP 200, 230 array elements (header plus 229 rows). The 229 rows are 223 with
status 404 and 6 with status 400 (status breakdown re-checked by the user). The final elements
are data rows, with no `[]` row and no key:

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
different digests of about 800 bytes. Of the 229 4xx rows in F3, 6 are 400 rather than 404
(status breakdown re-checked by the user).

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

### F11: httpx sends `^` unencoded (verified by the user on 2026-11-15)

Query (redirects followed, sent with httpx):
`GET https://web.archive.org/web/20050518204302id_/http://ichart.finance.yahoo.com:80/table.csv?s=^DJI&`

httpx raw request path:
`/web/20050518204302id_/http://ichart.finance.yahoo.com:80/table.csv?s=^DJI&`

Response: HTTP 200, 0 redirects. Headers excerpt:

```
Content-Type: text/csv
Memento-Datetime: Wed, 18 May 2005 20:43:02 GMT
```

The body is 44 bytes. Its base32(SHA-1) is `ASWL2AKBV45KRJN7BD5UYGRV4GPEDJRR`, equal to the CDX
digest of the same capture.

Observation: passing `original` unchanged through httpx works for raw `^` symbols; no
re-encoding is needed.

### F12: CSV header drift (verified by the user on 2026-11-15)

Query: the F11 capture. The 2005 body is header-only, with no data rows:

```
Date,Open,High,Low,Close,Volume,Adj. Close*
```

The 2013 and 2016 captures (F1, F5) use:

```
Date,Open,High,Low,Close,Volume,Adj Close
```

Observation: the header changed over the API's lifetime, and a header-only body is a valid
archived response. Exhume stores both as-is because it does no CSV parsing; format inference
is the Autopsy stage's job.

### F13: Live CDX listing sizes after client-side merge (verified by the user on 2026-11-20)

Run: `revenant.exhume.cdx.fetch_listing` (data pass, `limit=1000`, `resumeKey` pagination) for
each Host of `tombstones/yahoo-finance-ichart.toml`, with the default User-Agent, at least 1 second
between requests, 48 requests in total.

| Host | Unique digests after `merge_rows` | Pages | Years |
|---|---|---|---|
| ichart.yahoo.com | 10,620 | 15 | not reported |
| ichart.finance.yahoo.com | 19,317 | 27 | not reported |
| real-chart.finance.yahoo.com | 5,015 | 6 | 2014–2017 |

Observation: server-side `collapse=digest` only collapses ADJACENT rows; the CDX reported 14,651
rows for ichart.yahoo.com but only 10,620 digests are unique. Client-side de-duplication
(`merge_rows`, Requirement 3.4) is therefore required.

### F14: The Archive can substitute a different capture (verified by the user on 2026-11-20)

The Archive can answer an exact, existing timestamp with a 302 to a different capture; a retry
gets the exact one.

Kiro's live task 5.5 run requested
`https://web.archive.org/web/20041129204236id_/http://ichart.yahoo.com:80/table.csv?s=DISH&amp`
and got a 302 to `.../web/20050301233508id_/...`, then 200 with a 44-byte header-only body whose
digest `ASWL2AKBV45KRJN7BD5UYGRV4GPEDJRR` differs from the CDX digest
`2ADTBRSLGIS5YZLXF4LRCFLO363WOUXW`.

The user then requested the same URL 4 times (curl once, httpx with `follow_redirects=False`
three times). Each time: 200, 125 bytes, `Memento-Datetime: Mon, 29 Nov 2004 20:42:36 GMT`,
digest `2ADTBRSLGIS5YZLXF4LRCFLO363WOUXW` (matches the CDX).

Observation: the substitution is temporary and is not caused by `&amp`.

### F15: HTML-escaped crawler artifacts in `original` (verified by the user on 2026-11-20)

Rows whose `original` contains `&amp`:

| Host | Rows with `&amp` | Unique digests |
|---|---|---|
| ichart.yahoo.com | 8,151 | 10,620 |
| ichart.finance.yahoo.com | 6,132 | 19,317 |
| real-chart.finance.yahoo.com | 3 | 5,015 |

Example: `s=%5EVIX&amp;g=d&amp;ignore=.csv`. The responses are real Yahoo responses; `amp` is
not an API parameter.

### F16: Server comment line at the end of a body (verified by the user on 2026-11-20)

The 2004-11-29 DISH body (F14) ends with the server comment line:

```
<!-- ichart9.finance.scd.yahoo.com uncompressed Mon Nov 29 12:42:31 PST 2004 -->
```

### F17: Unrendered template junk in parameter values (verified by the user on 2026-11-20)

Source: the cached CDX listings under `evidence/yahoo-finance-ichart/cdx/` (no network).
2 rows carry unrendered template expressions in parameter values, for example
`c={{(-1 month).year}}`. Observation: selection must classify a non-numeric `a`–`f` value as
Parameter shape `other` and must never crash on `int()`.

### F18: Archived AAPL captures covering the demo range (verified by the user on 2026-11-20)

Source: the cached CDX listings (no network). 25 AAPL captures with timestamp >= `20160109`
cover 2016-01-04 to 2016-01-08: they have no `c`, `c` < 2016, or `c=2016` with `a=0`.
Examples: `20160405081912` on ichart.finance.yahoo.com (135,932 bytes, `g=d`, `c=1984`) and
`20160416023609` on real-chart.finance.yahoo.com (172,268 bytes, `g=d`, `c=1970`).
Observation: Yahoo's own archived full-history captures can serve as the primary donor.

### F19: Digest mismatches on chunked original responses (verified by the user on 2026-11-20)

The 4 entries of the N=50 run with `digest_verified: false` (ichart.finance.yahoo.com
`20120601181348`, `20120605013119`; real-chart.finance.yahoo.com `20141211083710`,
`20141217022734`) are genuine captures served at their exact timestamps. Re-fetches of
`20120601181348` (DPS) and `20141211083710` (YHOO) carry `x-archive-orig-transfer-encoding: chunked`;
the verified DISH capture (F14) does not. Observation: the CDX digest apparently covers the chunk
framing, which the Archive strips on replay. Re-framing the body as a single chunk did NOT
reproduce the digest, so the exact original chunking is unknown. These captures stay stored with
`digest_verified: false` (Requirement 7.6).

### F20: Archived servers ignored the requested range before 2008 (verified by the user with an independent classifier on 2026-11-21)

All 25 Unfit_Captures of the Autopsy month check except the one in F21 are from 2005 to 2007.
Yahoo ignored the end date (`d`/`e`/`f`) and returned rows through the last trading day before
the crawl; 3 of them also ignored the start date. No capture from 2014 on is Unfit, so the
2016-era servers respected the requested range.

### F21: Out-of-range month accepted (verified by the user with an independent classifier on 2026-11-21)

`ichart.finance.yahoo.com/20121217014635-DP2RNCXQZKYOFXDUCUXCL34SYCHTKAKU` requested `d=12`
(month 13 under 0-indexing) and got 61 monthly rows with no error.

### F22: Early `g=v` returned prices

2 `g=v` captures from 2005–2006 returned the price header (`Date,Open,High,Low,Close,Volume,Adj. Close*`), not `Date,Dividends`.
