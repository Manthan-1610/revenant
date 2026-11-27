# Revenant: Kiroween 2026 checklist

**Deadline: Fri Dec 4, 2:00 PM PT. Aim to submit by 10:00 AM PT.**
Category: Resurrection (+ Best Student Project, Best Demo, Blog prize).

**Status on Fri Nov 20:** setup is done (idea validated, death recorded, steering and Exhume
spec committed), but there is no code yet. We're about 5 days behind the original plan, so
every day below has a **must-have** line. If a day's must-have slips, apply that day's cut
rule. Don't just push everything back.

---

## Week 1: Fri Nov 20 – Thu Nov 26 (in detail)

### Fri Nov 20: admin + Exhume tasks 1–4
Admin (≈1 h)
- [x] Create the public GitHub repo **`Manthan-1610/revenant`** (the User-Agent already points there) *(done Sat)*
- [x] Add a `LICENSE` file (MIT or Apache-2.0), push `main`, and check that the license shows in the repo's About box *(MIT, pushed `074558b`)*
- [ ] Devpost: confirm you're registered for Kiroween 2026 and start a **draft** submission (title + one-liner)
- [ ] Have proof of student status ready (for the Best Student Project prize)
- [ ] Screen-record `victims/ystockquote` failing (the video's opening shot), if you haven't already
- [ ] Social post #1 with **#KiroweenHackathon26** ("Resurrecting the Yahoo Finance API that died in 2017"), for the Social Blitz prize

Exhume (Kiro Spec session, using the execution-rules prompt)
- [x] Task 1: scaffold, `.venv`, `pip install -e ".[dev]"`, `revenant --help` works
- [x] Task 2: models + Tombstone loader
- [x] Task 3: polite Archive client + P4 (rate limiter) property test
- [x] Task 4: CDX discovery + P1 (page parse) property test
- [x] **Must-have:** `pytest` is green and there are 4 commits named `exhume: task N` (45 tests; live CDX check passed on all 3 hosts)

### Sat Nov 21: first real capture (the vertical slice)
- [x] Task 5.1–5.4: store, naive run, CLI wiring, end-to-end mock test *(done Fri)*
- [x] Task 5.5: **live** `revenant exhume yahoo-finance-ichart --max-captures 1` writes a real CSV with `digest_verified: true` *(3/3 verified; the substituted-capture rule was added)*
- [x] Task 6: content checks + P2 (Offline detector) *(done Fri)*
- [x] Task 7: ethics filter + P5 (auth-parameter filter) *(done Fri)*
- [x] Donor scouting *(done Fri)*. **Decision: primary donor = Yahoo's own archived full-history captures** (25 AAPL captures after 2016-01-08 cover the demo range; 135–172 KB daily histories). Stooq is behind a JS bot wall (don't bypass it). Nasdaq has no 2016 data. Alpha Vantage works but needs a free key (25 requests/day, no Adj Close), so it's a stretch goal for dates after 2017.
- [ ] Get a free Alpha Vantage key (optional, stretch only)
- [x] **Must-have:** a real Yahoo capture is on disk and was fetched by our own code
- [ ] *Cut rule:* if task 5.5 fails by tonight, skip task 10 (error pass) on Sunday

### Sun Nov 22: finish Exhume + write the Autopsy spec
- [x] Task 8: deterministic selection + P3 (selection) property test *(done Fri; P3 found a real tie-break bug)*
- [x] Task 9: backfill, listing-cache reuse, idempotent reruns
- [x] Task 10: error pass
- [x] Task 11: Rich summary table + exit codes
- [x] Task 12: live smoke test (20 captures, ≥2 `g` values, ≥3 years, then 0 downloads on rerun)
- [x] Real run: `revenant exhume yahoo-finance-ichart` (N = 50), then **commit `evidence/`** *(160 entries, 10.1 MB; rerun takes 2.8 s with 0 downloads and a byte-identical index; verified by Claude)*
- [ ] Screenshot the Rich summary table for the video and blog (take it in Windows Terminal, full width)
- [x] Autopsy spec, **requirements only** *(8 requirements, 175 lines; the real evidence gives 53 captures that fit only 0-indexed months and 0 that fit only 1-indexed)*
- [x] **Must-have:** Exhume is done, evidence is committed, and Autopsy requirements are approved *(done Fri, 2 days early)*
- [ ] *Cut rule:* if Exhume isn't done tonight, drop task 10 and the parameter-shape groups (selection by interval only)

### Mon Nov 23: Autopsy, the part that works without AI
- [x] Autopsy design + tasks *(done Fri: 10 tasks, 198-line design)*
- [x] Infer the parameter list from archived URLs (names, value ranges, defaults) *(done Fri, task 5)*
- [x] **Infer that months are 0-indexed from evidence** *(done Fri: 58 decisive for 0-indexed, 0 for 1-indexed, 9 ambiguous, 25 unfit; Claude reproduced the exact counts independently)*
- [x] Detect header variants by year (`Adj. Close*` vs `Adj Close`), row order (newest first), and content type *(done Fri, task 6)*
- [x] Write `crypt/yahoo-finance-ichart/contract.json` *(vertical slice: months + source; byte-identical across runs)*
- [x] **Must-have:** `contract.json` exists and its facts match what `product.md` says *(done Fri; 197 tests pass)*

### Tue Nov 24: Autopsy, the generated spec + first Kiro hooks
- [x] Autopsy writes `.kiro/specs/revenant-yahoo-finance-ichart/requirements.md` (EARS) *(done Fri: 7 requirements, 129 lines; a renderer fix for value ranges is pending)* from `contract.json` with a **deterministic template** (reproducible and testable; Kiro CLI headless is saved for Reanimate, where it builds the server)
- [x] Hook 1, **"Test what you touched"**: when a file in `revenant/<stage>/` is saved, run `pytest tests/<stage> -q` *(committed Fri)*
- [x] Hook 2, **"Evidence integrity"**: on save or create under `evidence/`, run `revenant verify` and recommend `git checkout` on failure (it never restores files itself) *(committed Fri, plus the `revenant verify` command)*
- [x] Commit hooks under `.kiro/hooks/`
- [x] Fire both hooks once from a real IDE save (a shell can't trigger them) *(done Sat)*
- [x] **Install Kiro CLI + headless smoke test** *(kiro-cli 3.5.0, Google login, `--v3 --no-interactive` returned PULSE)*
- [ ] Social post #2 (the 0-indexed-month discovery)
- [x] **Must-have:** the generated spec exists, and 2 hooks are committed and have fired at least once

### Wed Nov 25: Reanimate
- [x] Reanimate spec (requirements + design + tasks, lean) *(done Thu: 7 requirements, 200-line design, 10 tasks; approved with 5 amendments)*
- [x] Autopsy precision fix: Yahoo_Number (F23) and `000` volume (F24) *(708,285 of 708,285 values; dividends use a fixed 6 decimals)*
- [x] Runner: `kiro-cli chat --v3 --no-interactive --trust-tools=<narrow list>` builds `crypt/<slug>/server.py` from the generated spec + `contract.json` *(done Thu Nov 26: first headless build passed on attempt 1, 46 s)*
- [x] Donor = Yahoo's own archived AAPL capture `20161222215700` (9,086 rows, 1980–2016), committed, so the server never needs the network *(it doesn't need a live donor or a replay fallback)*
- [x] **Must-have:** `curl "http://127.0.0.1:8000/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv"` returns CSV in the old format *(Claude verified: rows byte-identical to the archive)*
- [x] Reanimate tasks 5–10: scope check, import audit, redaction, full Build_Record, IDE fallback, all 3 Checks, optional donors, final rebuild *(done Thu: kiro-cli 3.6.2 rebuild passed all 3 Checks; 4 donors (AAPL, MSFT, ^GSPC, YHOO), Claude verified every served row verbatim against them; 354 tests)*

### Thu Nov 26 (Thanksgiving): light day
- [x] Fix whatever Wednesday left broken *(nothing was broken)*
- [x] Check that the revenant keeps every quirk: newest-first rows, header, `text/csv`, 0-indexed months *(Claude probed: month-12 rollover, day 31, template junk, unknown symbol, g=w, s-only, any Host header)*
- [ ] **Must-have:** none. Rest if you need to.

---

## Week 2: Fri Nov 27 – Fri Dec 4 (outline; detailed next Friday)

- [ ] **Fri 27, Pulse check:** Hypothesis tests built from archived samples (header, columns, row order, date range, content type)
- [ ] **Sat 28, Haunt:** mitmproxy addon that sends the 3 dead hosts to the revenant → `call_dead_api.py` logs **ALIVE** → screen-record it (THE demo moment)
- [ ] **Sun 29 – Mon 30, Graveyard UI:** tombstone page, evidence count, heart-monitor animation driven by pulse results, a "try it" box
- [ ] **Tue Dec 1, ship:** deploy (one container, stays up until Jan 29, 2027), README, Kiro write-up draft, optional MCP wrapper/Power if time allows
- [ ] **Wed Dec 2, video:** script → record → edit, under 3:00, public on YouTube
- [ ] **Thu Dec 3, words:** Devpost write-up (how Kiro was used: specs, hooks, steering, headless, property-based tests), blog post (Blog prize), social post #3
- [ ] **Fri Dec 4, submit by 10 AM PT:** final checks (repo public, license visible, `/.kiro` present, demo URL works logged-out, video public)

## Cut list (already decided, don't revisit)
- ✂️ Kiro Crew "Graveyard Watch" app
- ✂️ Second API (YQL)
- ✂️ HTTPS interception
- ✂️ Kiro Power packaging. Only if Dec 1 has spare time.

## Prizes we're aiming for
- [ ] Best Resurrection, or a top-3 overall place
- [ ] Best Student Project – Resurrection
- [ ] Best Demo
- [ ] Blog prize (public post during the submission period)
- [ ] Social Blitz (posts tagged #KiroweenHackathon26)
