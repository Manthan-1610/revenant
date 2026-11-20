---
inclusion: always
---

# Product: Revenant

## One-liner
Revenant resurrects dead cloud APIs from their remains in the Internet Archive, so the
apps, scripts and devices that depended on them work again — without changing them.

## The problem
When a company shuts down an API, everything built on it dies too: scripts, spreadsheets,
apps, and sometimes hardware (Spotify Car Thing, Humane AI Pin). Communities like Rebble
(Pebble smartwatches) have spent years rebuilding dead servers by hand. Revenant automates
that work.

## Who it is for
- Developers and analysts whose old scripts broke when an API died.
- Owners of devices bricked by a cloud shutdown.
- Digital-preservation people who want old software to keep running.

## How it works: five stages
Each stage is its own module and its own Kiro spec.

1. **Exhume**: collect evidence for a dead API slug across all of its hostnames, as listed
   in its tombstone (`tombstones/<slug>.toml`). This means archived responses from the
   Wayback Machine CDX API. Archived docs pages and the requests that old client code makes
   (`urls_called` in victim run logs) come later, not in the Exhume MVP.
2. **Autopsy**: infer the API contract (endpoints, parameters, response format, quirks)
   from the evidence. Write it as `contract.json` plus a generated Kiro spec.
3. **Reanimate**: implement the contract as a FastAPI server, backed by a living
   "organ donor" data source. Kiro CLI headless mode does the implementation.
4. **Pulse check**: property-based tests (Hypothesis) built from the archived responses
   prove the new server honours the old contract. The UI shows them as a heart monitor.
5. **Haunt**: route an unmodified old client to the revenant through a local proxy
   (mitmproxy, via `HTTP_PROXY`).

## Hero API: Yahoo Finance historical prices (died 2017)
The same API was served on three hostnames. The DNS for all three no longer resolves:
- `http://ichart.yahoo.com/table.csv` (used by ystockquote 0.2.4, our demo victim)
- `http://ichart.finance.yahoo.com/table.csv` (used by pandas-datareader 0.2.x)
- `http://real-chart.finance.yahoo.com/table.csv` (used by ystockquote 0.2.5)

Contract facts verified from archived captures and old client code:
- Query params: `s` symbol; `a`,`b`,`c` = start month, day, year; `d`,`e`,`f` = end
  month, day, year; `g` = interval (`d`, `w`, `m`); `ignore=.csv`.
- **Months are 0-indexed** (`a=0` means January). Clients do `int(month) - 1`.
- Responses are `text/csv`.
- The CSV header changed over time: `Adj. Close*` (2005) vs `Adj Close` (2016) (F12).
  Autopsy must detect format variants by capture year; a header-only body (no rows) is
  a valid response.
- **Rows are newest first.**
- Every quirk must be preserved. Old clients depend on them.

Archived evidence (CDX, unique captures by digest, checked 2026-11-15):
- Data captures (`200 text/csv`): ichart.yahoo.com has 14,651 (2004–2017).
  ichart.finance.yahoo.com has 22,209 (2004–2017). real-chart.finance.yahoo.com has not
  been checked yet.
- Error captures for ichart.yahoo.com: 229 (223 × 404, 6 × 400, all text/html).
- Captures include `g=d` and `g=w` intervals. ichart.finance.yahoo.com also has `g=m` (37)
  and `g=v` (18); `g=v` is not one of the documented intervals.
- Captured requests include ones with only `s`, and ones with empty `a`–`g` values. Autopsy
  must determine the default behaviour. Index symbols arrive both raw (`s=^DJI`) and
  percent-encoded (`s=%5EAEX`).

Second API (stretch): Yahoo YQL (`query.yahooapis.com/v1/public/yql`, XML, died 2019).

## The demo moment
An unmodified 2013 library (`victims/ystockquote`) fails today with a DNS error. After
Revenant runs, the same command, unchanged, returns real price data. "It's alive."

## Hackathon context
- Kiroween 2026, **Resurrection** category. Solo student entry.
- Deadline: Fri 2026-12-04, 2:00 PM PT.
- Judging, each 20%: Potential Impact, Technological Implementation (depth of Kiro use),
  Design, Innovation, Presentation (3-minute video).
- Priority order when time is short: (1) one API resurrected end to end, (2) visible
  pulse check, (3) graveyard UI, (4) Kiro Power packaging, (5) second API.

## Non-goals
- Not "any device": the MVP haunts plain-HTTP clients via `HTTP_PROXY` only. HTTPS
  interception (non-pinned, with consent) is a stretch goal; pinned clients are out of scope.
- Not a trading data source: no accuracy guarantees beyond the donor's data.
- Not a general web scraper.
