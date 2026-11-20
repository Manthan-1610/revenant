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
- [ ] Create the public GitHub repo **`Manthan-1610/revenant`** (the User-Agent already points there)
- [ ] Add a `LICENSE` file (MIT or Apache-2.0), push `main`, and check that the license shows in the repo's About box
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
- [ ] Task 5.1–5.4: store, naive run, CLI wiring, end-to-end mock test
- [ ] Task 5.5: **live** `revenant exhume yahoo-finance-ichart --max-captures 1` writes a real CSV with `digest_verified: true` (paste the output to Claude to double-check)
- [ ] Task 6: content checks + P2 (Offline detector)
- [ ] Task 7: ethics filter + P5 (auth-parameter filter)
- [ ] Donor scouting (30 min): pick the live source of daily price data. Test 2–3 free options with curl and note rate limits and whether each needs a key. Write the choice in `tech.md`.
- [ ] **Must-have:** a real Yahoo capture is on disk and was fetched by our own code
- [ ] *Cut rule:* if task 5.5 fails by tonight, skip task 10 (error pass) on Sunday

### Sun Nov 22: finish Exhume + write the Autopsy spec
- [ ] Task 8: deterministic selection + P3 (selection) property test
- [ ] Task 9: backfill, listing-cache reuse, idempotent reruns
- [ ] Task 10: error pass
- [ ] Task 11: Rich summary table + exit codes
- [ ] Task 12: live smoke test (20 captures, ≥2 `g` values, ≥3 years, then 0 downloads on rerun)
- [ ] Real run: `revenant exhume yahoo-finance-ichart` (N = 50), then **commit `evidence/`**
- [ ] Screenshot the Rich summary table for the video and blog
- [ ] Autopsy spec, **requirements only** (Spec session, with the same discipline: ≤10 requirements, ≤250 lines)
- [ ] **Must-have:** Exhume is done, evidence is committed, and Autopsy requirements are approved
- [ ] *Cut rule:* if Exhume isn't done tonight, drop task 10 and the parameter-shape groups (selection by interval only)

### Mon Nov 23: Autopsy, the part that works without AI
- [ ] Autopsy design + tasks (max 1 review round each)
- [ ] Infer the parameter list from archived URLs (names, value ranges, defaults)
- [ ] **Infer that months are 0-indexed from evidence**: compare the requested `a/b/c` with the first date in each response body (this is a demo moment)
- [ ] Detect header variants by year (`Adj. Close*` vs `Adj Close`), row order (newest first), and content type
- [ ] Write `crypt/yahoo-finance-ichart/contract.json`
- [ ] **Must-have:** `contract.json` exists and its facts match what `product.md` says

### Tue Nov 24: Autopsy, the generated spec + first Kiro hooks
- [ ] Autopsy writes `.kiro/specs/revenant-yahoo-finance-ichart/requirements.md` (EARS) from `contract.json`, using **Kiro CLI headless** for the prose (no separate LLM key needed)
- [ ] Hook 1, **"Test what you touched"**: when a file in `revenant/<stage>/` is saved, run `pytest tests/<stage> -q`
- [ ] Hook 2, **"Evidence is immutable"**: if a file under `evidence/` is edited, restore it from git and explain why (protects digest integrity)
- [ ] Commit hooks under `.kiro/hooks/`
- [ ] Social post #2 (the 0-indexed-month discovery)
- [ ] **Must-have:** the generated spec exists, and 2 hooks are committed and have fired at least once

### Wed Nov 25: Reanimate
- [ ] Reanimate spec (requirements + design + tasks, lean)
- [ ] Runner: `kiro-cli chat --v3 --no-interactive --trust-tools=<narrow list>` builds `crypt/<slug>/server.py` from the generated spec + `contract.json`
- [ ] Donor adapter (the live source from Saturday) + **offline replay fallback** (serve archived evidence when the donor fails, so the judges' demo never dies)
- [ ] **Must-have:** `curl "http://127.0.0.1:8000/table.csv?s=AAPL&a=0&b=4&c=2016&d=0&e=8&f=2016&g=d&ignore=.csv"` returns CSV in the old format

### Thu Nov 26 (Thanksgiving): light day
- [ ] Fix whatever Wednesday left broken
- [ ] Check that the revenant keeps every quirk: newest-first rows, header, `text/csv`, 0-indexed months
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
