"""End-to-end example tests for the thin vertical slice (store, run, CLI)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from revenant import cli
from revenant.exhume.archive import DEFAULT_USER_AGENT, ArchiveClient, RateLimiter, make_client
from revenant.exhume.content import wayback_digest
from revenant.exhume.models import HostSummary, Tombstone
from revenant.exhume.run import exhume, served_timestamp, wayback_url
from revenant.exhume.store import EvidenceStore
from tests.exhume.conftest import FakeClock

HOST = "ichart.yahoo.com"
F5_BODY = (
    b"Date,Open,High,Low,Close,Volume,Adj Close\n"
    b"2010-01-25,546.59,549.88,525.61,529.94,4021800,529.94\n"
    b"2010-01-19,581.20,590.42,534.86,550.01,5168800,550.01\n"
)
HK298_BODY = b"Date,Open,High,Low,Close,Volume,Adj Close\n2009-01-02,1.00,1.10,0.90,1.05,100,1.05\n"
# Three F1 rows, merged order (timestamp, digest): 0298.HK, 0005.HK, GOOG.
ROW_HK298 = (
    "20090103230517",
    "http://ichart.yahoo.com:80/table.csv?s=0298.HK&d=0&e=1&f=2009&g=d&a=0&b=1&c=2003&ignore=.csv",
    wayback_digest(HK298_BODY),  # the F6 redirect serves the same content: not a substitution
)
ROW_HK005 = (
    "20090129101731",
    "http://ichart.yahoo.com:80/table.csv?s=0005.HK&a=0&b=1&c=2003&d=0&e=20&f=2009&g=d&ignore=.csv",
    "IHBKV5JJ7OXMYBPR2BZY25W2Q6GNQSBG",
)
ROW_GOOG = (
    "20131213174436",
    "http://ichart.yahoo.com:80/table.csv?s=GOOG&a=0&b=1&c=2000&d=0&e=31&f=2010&g=w&ignore=.csv",
    wayback_digest(F5_BODY),  # so this capture verifies
)
REDIRECT_TS = "20090103231000"  # where the 0298.HK capture is "actually" served (F6-style)

CDX_PAGE = json.dumps(
    [
        ["timestamp", "original", "mimetype", "statuscode", "digest", "length"],
        [ROW_GOOG[0], ROW_GOOG[1], "text/csv", "200", ROW_GOOG[2], "6731"],
        [ROW_HK298[0], ROW_HK298[1], "text/csv", "200", ROW_HK298[2], "14808"],
        [ROW_HK005[0], ROW_HK005[1], "text/csv", "200", ROW_HK005[2], "22849"],
    ]
).encode()

INDEX_FIELDS = {
    "host",
    "kind",
    "requested_timestamp",
    "served_timestamp",
    "original",
    "mimetype",
    "statuscode",
    "digest",
    "length",
    "final_url",
    "path",
    "size",
    "sha256",
    "content_type",
    "digest_verified",
    "fetched_at",
}


class FakeArchive:
    """MockTransport handler: one CDX page, an F6 redirect, Memento-Datetime and a 404."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/cdx/search/cdx":
            return httpx.Response(
                200, content=CDX_PAGE, headers={"Content-Type": "application/json"}
            )
        if path.startswith(f"/web/{ROW_HK298[0]}id_/"):
            target = wayback_url(REDIRECT_TS, ROW_HK298[1].replace(":80", ""))
            return httpx.Response(302, headers={"Location": target})
        if path.startswith(f"/web/{REDIRECT_TS}id_/"):
            return httpx.Response(200, content=HK298_BODY, headers={"Content-Type": "text/csv"})
        if path.startswith(f"/web/{ROW_GOOG[0]}id_/"):
            return httpx.Response(
                200,
                content=F5_BODY,
                headers={
                    "Content-Type": "text/csv",
                    "Memento-Datetime": "Fri, 13 Dec 2013 17:44:36 GMT",
                },
            )
        if path.startswith(f"/web/{ROW_HK005[0]}id_/"):
            return httpx.Response(404, content=b"<html>not archived</html>")
        raise AssertionError(f"unexpected request {request.url}")


def _tombstone() -> Tombstone:
    return Tombstone(
        slug="yahoo-finance-ichart",
        name="Yahoo Finance historical prices",
        died="2017-05",
        hosts=[HOST],
        paths=["table.csv"],
        mimetypes=["text/csv"],
    )


def test_end_to_end_data_pass(tmp_path: Path) -> None:
    fake = FakeArchive()
    clock = FakeClock()
    client = make_client(RateLimiter(clock), DEFAULT_USER_AGENT, httpx.MockTransport(fake))
    store = EvidenceStore(tmp_path, "yahoo-finance-ichart")

    result = exhume(_tombstone(), store, ArchiveClient(client, clock), 3, False)

    [summary] = result.hosts
    assert (summary.found, summary.downloaded, summary.cached, summary.rejected) == (3, 2, 0, 1)
    assert summary.discovery_failed == []
    assert result.error_evidence == 0

    # The 404 data capture was requested exactly once (no retry).
    hk005 = [r for r in fake.requests if r.url.path.startswith(f"/web/{ROW_HK005[0]}id_/")]
    assert len(hk005) == 1
    # `original` reaches the Archive unchanged, including `:80`.
    assert str(hk005[0].url) == wayback_url(ROW_HK005[0], ROW_HK005[1])

    slug_dir = tmp_path / "yahoo-finance-ichart"
    assert (slug_dir / "cdx" / f"{HOST}.json").is_file()
    index = json.loads((slug_dir / "index.json").read_bytes())
    assert index["slug"] == "yahoo-finance-ichart"
    assert set(index["entries"]) == {
        f"{HOST}/{ROW_HK298[0]}-{ROW_HK298[2]}",
        f"{HOST}/{ROW_GOOG[0]}-{ROW_GOOG[2]}",
    }
    for key, entry in index["entries"].items():
        assert set(entry) == INDEX_FIELDS
        assert entry["path"] == f"{key}.csv"
        body = (slug_dir / entry["path"]).read_bytes()
        expected = HK298_BODY if entry["requested_timestamp"] == ROW_HK298[0] else F5_BODY
        assert body == expected
        assert entry["size"] == len(expected)
        assert entry["kind"] == "data"
        assert entry["digest_verified"] == (wayback_digest(body) == entry["digest"])

    redirected = index["entries"][f"{HOST}/{ROW_HK298[0]}-{ROW_HK298[2]}"]
    assert redirected["requested_timestamp"] == ROW_HK298[0]
    assert redirected["served_timestamp"] == REDIRECT_TS
    assert redirected["digest_verified"] is True

    memento = index["entries"][f"{HOST}/{ROW_GOOG[0]}-{ROW_GOOG[2]}"]
    assert memento["served_timestamp"] == "20131213174436"
    assert memento["digest_verified"] is True
    assert memento["content_type"] == "text/csv"

    # Index bytes are stable: sorted keys, indent 2, trailing newline.
    raw = (slug_dir / "index.json").read_bytes()
    assert raw.endswith(b"}\n")
    assert raw == (json.dumps(index, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


# F14: the Archive 302s an exact DISH timestamp to a different capture; a retry gets the exact one.
DISH_TS = "20041129204236"
DISH_ORIGINAL = "http://ichart.yahoo.com:80/table.csv?s=DISH&amp"
DISH_BODY = b"Date,Open,High,Low,Close,Volume,Adj. Close*\n2004-11-26,1,1,1,1,1,1\n"
SUBSTITUTE_TS = "20050301233508"
SUBSTITUTE_BODY = b"Date,Open,High,Low,Close,Volume,Adj. Close*\n"


class SubstitutingArchive:
    """One-row CDX page; capture replies follow a script of 'substitute' / 'exact' / 'stale'."""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.capture_fetches = 0
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/cdx/search/cdx":
            page = [
                ["timestamp", "original", "mimetype", "statuscode", "digest", "length"],
                [DISH_TS, DISH_ORIGINAL, "text/csv", "200", wayback_digest(DISH_BODY), "125"],
            ]
            return httpx.Response(200, content=json.dumps(page).encode())
        if path.startswith(f"/web/{DISH_TS}id_/"):
            self.capture_fetches += 1
            step = self.script.pop(0)
            if step == "substitute":
                target = wayback_url(SUBSTITUTE_TS, DISH_ORIGINAL.replace(":80", ""))
                return httpx.Response(302, headers={"Location": target})
            body = DISH_BODY if step == "exact" else SUBSTITUTE_BODY
            headers = {
                "Content-Type": "text/csv",
                "Memento-Datetime": "Mon, 29 Nov 2004 20:42:36 GMT",
            }
            return httpx.Response(200, content=body, headers=headers)
        if path.startswith(f"/web/{SUBSTITUTE_TS}id_/"):
            return httpx.Response(
                200, content=SUBSTITUTE_BODY, headers={"Content-Type": "text/csv"}
            )
        raise AssertionError(f"unexpected request {request.url}")


def _run_substitution(
    tmp_path: Path, script: list[str]
) -> tuple[SubstitutingArchive, FakeClock, HostSummary]:
    fake = SubstitutingArchive(script)
    clock = FakeClock()
    client = make_client(RateLimiter(clock), DEFAULT_USER_AGENT, httpx.MockTransport(fake))
    store = EvidenceStore(tmp_path, "yahoo-finance-ichart")
    result = exhume(_tombstone(), store, ArchiveClient(client, clock), 1, False)
    [summary] = result.hosts
    return fake, clock, summary


def test_substituted_then_exact_capture_is_stored(tmp_path: Path) -> None:
    fake, clock, summary = _run_substitution(tmp_path, ["substitute", "exact"])
    assert (summary.downloaded, summary.rejected) == (1, 0)
    assert fake.capture_fetches == 2

    index = json.loads((tmp_path / "yahoo-finance-ichart" / "index.json").read_bytes())
    [entry] = index["entries"].values()
    assert entry["requested_timestamp"] == DISH_TS
    assert entry["served_timestamp"] == DISH_TS
    assert entry["digest_verified"] is True
    assert (tmp_path / "yahoo-finance-ichart" / entry["path"]).read_bytes() == DISH_BODY
    # The re-fetch went through the same rate-limited client: 1 CDX + (302 + hop) + 1 exact.
    assert len(fake.requests) == 4
    assert clock.monotonic() >= len(fake.requests) - 1


def test_substituted_twice_is_rejected(tmp_path: Path) -> None:
    fake, _, summary = _run_substitution(tmp_path, ["substitute", "substitute"])
    assert (summary.downloaded, summary.rejected) == (0, 1)
    assert fake.capture_fetches == 2

    slug_dir = tmp_path / "yahoo-finance-ichart"
    assert not (slug_dir / HOST).exists()
    assert not (slug_dir / "index.json").exists()


def test_same_timestamp_digest_mismatch_is_stored_unverified(tmp_path: Path) -> None:
    # Req 7.6: served == requested, so a mismatch is not a substitution; no re-fetch.
    fake, _, summary = _run_substitution(tmp_path, ["stale"])
    assert (summary.downloaded, summary.rejected) == (1, 0)
    assert fake.capture_fetches == 1
    index = json.loads((tmp_path / "yahoo-finance-ichart" / "index.json").read_bytes())
    [entry] = index["entries"].values()
    assert entry["digest_verified"] is False


def test_served_timestamp_fallbacks() -> None:
    plain = httpx.Request("GET", "https://example.test/no-wayback-path")
    memento = httpx.Response(
        200, headers={"Memento-Datetime": "Wed, 09 Jun 2004 20:30:20 GMT"}, request=plain
    )
    assert served_timestamp(memento) == "20040609203020"
    assert served_timestamp(httpx.Response(200, request=plain)) is None


def test_cli_invalid_tombstone_sends_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "tombstones").mkdir()
    (tmp_path / "tombstones" / "broken.toml").write_text('slug = "broken"\nname = "x"\n')
    monkeypatch.chdir(tmp_path)

    def no_client(*args: object, **kwargs: object) -> httpx.Client:
        raise AssertionError("an HTTP client was created for an invalid Tombstone")

    monkeypatch.setattr(cli, "make_client", no_client)
    result = CliRunner().invoke(cli.app, ["exhume", "broken"])
    assert result.exit_code == 1
    assert "broken.toml" in result.output
    assert "hosts" in result.output
    assert not (tmp_path / "evidence").exists()
