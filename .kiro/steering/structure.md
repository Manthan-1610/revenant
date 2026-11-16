---
inclusion: always
---

# Project structure

```
revenant/                 Python package (the product)
  exhume/                 Wayback CDX client, capture fetcher, evidence store
  autopsy/                contract inference -> contract.json -> generated Kiro spec
  reanimate/              Kiro CLI headless runner, donor registry
  pulse/                  Hypothesis test generation and runner
  haunt/                  mitmproxy addon and routing table (dead host -> revenant)
  api/                    FastAPI app: dashboard API, mounts the revenants from crypt/
tombstones/<slug>.toml    one manifest per dead API: Exhume's input
evidence/<slug>/<host>/   Wayback evidence: the capped capture sample (raw bytes + metadata)
evidence/<slug>/index.json  index of every capture Exhume kept for the slug
crypt/<slug>/             one revenant per folder (server, contract.json, pulse tests)
web/                      React + Vite + Tailwind graveyard UI
victims/<client>/         untouched old clients that prove a resurrection works
tests/<stage>/            unit and integration tests, one folder per revenant/ stage
.kiro/                    specs, hooks, steering (always committed)
```

## Naming
- **Revenant** is the product and its Python package, `revenant/`. **A revenant** is one
  resurrected API. Each one lives in `crypt/<slug>/`.
- An API slug is `<vendor>-<api>`, for example `yahoo-finance-ichart`.
- One slug can serve several dead hostnames. The routing table maps host -> slug.
- Contracts live at `crypt/<slug>/contract.json`. The contract is the source of truth.
  Kiro CLI writes servers and tests from it; to change behaviour, change the contract and
  regenerate. The Autopsy spec for a slug lives at `.kiro/specs/revenant-<slug>/`.
- Specs for building each stage live at `.kiro/specs/<stage>/`, for example
  `.kiro/specs/exhume/`.

## Tombstones
One TOML manifest per dead API, named after its slug. Exhume reads it and collects
evidence across every listed host.

```toml
# tombstones/yahoo-finance-ichart.toml
slug = "yahoo-finance-ichart"
name = "Yahoo Finance historical prices"
died = "2017-05"
hosts = ["ichart.yahoo.com", "ichart.finance.yahoo.com", "real-chart.finance.yahoo.com"]
paths = ["table.csv"]
mimetypes = ["text/csv"]
```

## Evidence
Two separate stores, both committed:
- **Wayback evidence**: `evidence/<slug>/<host>/` plus `evidence/<slug>/index.json`. Only
  the capped sample Exhume downloads, never a full mirror. This is Autopsy's input.
- **Victim run logs**: `victims/<client>/evidence/`. DEAD or ALIVE logs written by
  `call_dead_api.py`. Reading their `urls_called` as client-request evidence comes later,
  not in the Exhume MVP.

## Victims
Each victim folder pins the original package version from PyPI and runs it unmodified.
`call_dead_api.py` writes a timestamped run log (DEAD or ALIVE) to
`victims/<client>/evidence/`.
