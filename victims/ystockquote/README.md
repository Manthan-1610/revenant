# Victim: ystockquote 0.2.4

A Python library for Yahoo Finance data. It was published on PyPI in August 2013 under
LGPLv2+ by Corey Goldberg (https://github.com/cgoldberg/ystockquote). Its
`get_historical_prices()` calls `http://ichart.yahoo.com/table.csv`, which Yahoo shut
down in 2017. That hostname no longer resolves in DNS.

The library is installed from PyPI exactly as published, and it is not vendored or modified
in this repo. `call_dead_api.py` checks the installed file's SHA-256 against the published
source to prove that.

## Record its death

```bash
cd victims/ystockquote
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
.venv/Scripts/python call_dead_api.py
```

## Record its resurrection (after Haunt exists)

PowerShell (Windows):

```powershell
$env:HTTP_PROXY = 'http://127.0.0.1:8080'; .venv/Scripts/python call_dead_api.py
```

bash (macOS/Linux):

```bash
HTTP_PROXY=http://127.0.0.1:8080 .venv/bin/python call_dead_api.py
```

Each run writes `evidence/<timestamp>-dead.json` or `evidence/<timestamp>-alive.json`.
