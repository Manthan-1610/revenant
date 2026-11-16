---
inclusion: always
---

# Tech stack and conventions

## Stack
- **Python 3.12** for everything server-side. Packaging is defined in `pyproject.toml`.
- **FastAPI + uvicorn**: the dashboard API, plus the resurrected API servers ("revenants").
- **httpx** for outbound HTTP (Wayback Machine, donor APIs). Use async where it helps.
- **Pydantic v2** for every data model, especially the API contract (`contract.json`).
- **pytest + Hypothesis** for tests. Hypothesis is the pulse check.
- **mitmproxy** (Python addon) for the Haunt stage.
- **LLM for Autopsy**: Amazon Bedrock or the Claude API behind one small interface
  (`revenant/autopsy/llm.py`). Cache every LLM result on disk by input hash.
- **Frontend**: React + Vite + TypeScript + Tailwind in `web/`. FastAPI serves the built
  files, so production is a single Docker container.

## Wayback Machine etiquette (mandatory)
- Discover captures with the CDX API:
  `https://web.archive.org/cdx/search/cdx?url=<host>/<path>*&output=json&collapse=digest`
- Fetch raw captures with the `id_` form: `https://web.archive.org/web/<timestamp>id_/<url>`.
- Use `follow_redirects=True`. The Archive can serve a capture from a different timestamp
  than the one requested, so record the timestamp actually served.
- Data captures: status 2xx and a mimetype listed in the slug's tombstone.
- Also keep 4xx captures, capped at 10 per API; tagged as error-behaviour evidence; never
  used as data.
- Wait at least 1 second between requests. Retry with exponential backoff.
- The Archive sometimes returns an HTML "Temporarily Offline" page with status 200.
  Detect it and treat it as a retryable failure, never as evidence.
- Cache every capture under `evidence/<slug>/<host>/` and list it in
  `evidence/<slug>/index.json`, so you never fetch the same capture twice.

## Kiro CLI headless (Reanimate stage)
See `kiro-headless.md`, which loads when you work on Reanimate files.

## Conventions
- Type hints everywhere. Format and lint with ruff.
- Small modules: one stage per package under `revenant/`.
- An endpoint counts as alive only when both hold: its Hypothesis pulse tests pass, and the
  victim's run log records ALIVE through Haunt.
- Unit tests never touch the network: use `httpx.MockTransport` with fixtures from
  `evidence/`. Live tests carry `@pytest.mark.live` and are skipped by default via
  `addopts = "-m 'not live'"` in `pyproject.toml`.
- Keep secrets in `.env`, which is gitignored. Commit `.env.example` instead.
- Never add `.kiro/` to `.gitignore`. Doing so can disqualify the entry.
