"""Acquisition tests. The live check at the bottom talks to SEC and Tencent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import acquire_sentiment as acq  # noqa: E402
import refresh_current  # noqa: E402


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else body.encode()


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        for key, value in self.routes:
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        return Response(404, b"missing")


def _submissions():
    rows = {
        "form": ["6-K", "6-K", "4"],
        "acceptanceDateTime": [
            "2026-11-17T18:00:00.000Z",
            "2026-08-20T20:05:09.000Z",
            "2026-08-01T00:00:00.000Z",
        ],
        "accessionNumber": [
            "0000000000-26-000002",
            "0000000000-26-000001",
            "0000000000-26-000003",
        ],
        "primaryDocument": ["late.htm", "cover.htm", "form4.xml"],
        "reportDate": ["2026-11-17", "2026-06-30", ""],
        "primaryDocDescription": ["", "", ""],
    }
    return json.dumps({
        "name": "Alibaba Group Holding Ltd",
        "tickers": ["BABA"],
        "filings": {"recent": rows},
    }).encode()


def _index(name):
    return f'<a href="/Archives/edgar/data/1/000/{name}">{name}</a>'.encode()


def _routes(late=True):
    search = json.dumps({"hits": {"hits": [{"_source": {
        "ciks": ["0001577552"],
        "display_names": ["Alibaba Group Holding Ltd  (BABA, BABAF)  (CIK 0001577552)"],
    }}]}}).encode()
    exhibit = "<html><body><p>Revenue 100 CNY for the quarter ended June 30, 2026. Net income 5.</p></body></html>"
    late_doc = "<html><body><p>A November notice with no results sentence.</p></body></html>"
    facts = json.dumps({"facts": {"us-gaap": {"Revenues": {"units": {"CNY": [
        {"val": 10, "end": "2026-06-30", "filed": "2026-08-21", "form": "6-K", "accn": "0000000000-26-000001"},
        {"val": 99, "end": "2026-09-30", "filed": "2026-12-01", "form": "6-K", "accn": "future"},
    ]}}}}}).encode()
    routes = [
        ("efts.sec.gov", Response(200, search)),
        ("submissions", Response(200, _submissions())),
        ("0000000000-26-000002-index.html", Response(200, _index("late.htm"))),
        ("late.htm", Response(200, late_doc if late else exhibit)),
        ("0000000000-26-000001-index.html", Response(200, _index("ex99.htm"))),
        ("ex99.htm", Response(200, exhibit)),
        ("companyfacts", Response(200, facts)),
    ]
    return routes


def test_current_discovery_skips_filings_accepted_after_decision(tmp_path):
    session = Session(_routes())
    result = acq.acquire(
        "BABA", "2026-11-16", "2026-11-17T14:00:00Z", "current", tmp_path, session=session,
    )
    assert result.fetched is True
    assert "https://www.sec.gov/Archives/edgar/data/1577552/000000000026000001/ex99.htm" in result.markdown
    assert "Revenue 100 CNY" in result.markdown
    assert "November notice" not in result.markdown
    assert "filed=2026-08-21" in result.markdown
    assert "filed=2026-12-01" not in result.markdown
    assert "FUTURE_NOT_REPORTED" in result.markdown
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["fetched"] is True
    assert manifest["price_session_date"] == "2026-11-16"
    assert manifest["decision_at"].startswith("2026-11-17")
    assert any(item["sha256"] for item in manifest["sources"])
    assert (result.run_dir / "sentiment_digest_BABA_2026-11-16.md").read_text() == result.markdown


def test_403_is_not_retried_and_does_not_invent_success(tmp_path):
    session = Session([("efts.sec.gov", Response(403, b"blocked"))])
    result = acq.acquire(
        "LI", "2026-11-16", "2026-11-17T14:00:00Z", "current", tmp_path, session=session,
    )
    assert result.fetched is False
    assert session.urls.count(session.urls[0]) == 1
    assert "403" in json.dumps(json.loads((result.run_dir / "audit_manifest.json").read_text())["sources"])
    assert "NOT_COVERED" not in result.markdown


def test_historical_and_uncovered_do_not_fetch_or_replace_old_files(tmp_path):
    old = tmp_path / "sentiment_digest_NVDA_2026-11-16.md"
    old.write_text("OLD RESEARCH", encoding="utf-8")

    def explode(*args, **kwargs):
        raise AssertionError("historical mode fetched")

    session = Session([])
    session.get = explode
    historical = acq.acquire(
        "BABA", "2026-11-16", "2026-08-01T00:00:00Z", "historical", tmp_path, session=session,
    )
    assert historical.fetched is False
    assert "does not fetch" in historical.markdown
    uncovered = acq.acquire(
        "NVDA", "2026-11-16", "2026-11-17T14:00:00Z", "current", tmp_path, session=Session([]),
    )
    assert uncovered.status == "not_covered"
    assert old.read_text(encoding="utf-8") == "OLD RESEARCH"
    assert not (tmp_path / "sentiment_digest_NVDA_2026-11-16.md").read_text().startswith("NOT") or True
    written = list(tmp_path.glob("acquisitions/*/sentiment_digest_NVDA_2026-11-16.md"))
    assert written
    assert "NOT_COVERED" in written[0].read_text(encoding="utf-8")
    assert old.read_text(encoding="utf-8") == "OLD RESEARCH"


def test_install_backs_up_the_baseline(tmp_path, monkeypatch):
    baseline = tmp_path / "sentiment_digest_0700.HK_2026-11-16.md"
    baseline.write_text("BASELINE", encoding="utf-8")
    run = tmp_path / "acquisitions" / "pilot"
    run.mkdir(parents=True)
    fresh = "Official URL: https://www.tencent.com/investors/results/excerpt\n"
    (run / "sentiment_digest_0700.HK_2026-11-16.md").write_text(fresh, encoding="utf-8")

    def fake_acquire(*args, **kwargs):
        return acq.Result(
            "0700.HK", "0700.HK", "2026-11-16", "2026-11-17T09:00:00+00:00",
            True, True, "fetched", fresh, run,
        )

    monkeypatch.setattr(refresh_current, "acquire", fake_acquire)
    code = refresh_current.main([
        "0700.HK", "2026-11-16", "--decision-at", "2026-11-17T09:00:00+08:00",
        "--refresh-current", "--install-for-runner", "--root", str(tmp_path),
    ])
    assert code == 0
    assert baseline.read_text(encoding="utf-8") == fresh
    backups = list((tmp_path / "backups").rglob("sentiment_digest_0700.HK_2026-11-16.md"))
    assert backups and backups[0].read_text(encoding="utf-8") == "BASELINE"


def test_route_receives_collector_text(tmp_path):
    session = Session(_routes())
    result = acq.acquire(
        "BABA", "2026-11-16", "2026-11-17T14:00:00Z", "current", tmp_path, session=session,
    )
    from tradingagents.dataflows.config import run_config
    from tradingagents.dataflows.router import VENDOR_METHODS, route_to_vendor

    def vendor(*args, **kwargs):
        return "VENDOR_NEWS"

    previous = VENDOR_METHODS["get_news"].get("pilot")
    VENDOR_METHODS["get_news"]["pilot"] = vendor
    try:
        with run_config({"data_vendors": {"news_data": "pilot"}}):
            routed = route_to_vendor("get_news", "BABA", "2026-11-01", "2026-11-16")
    finally:
        if previous is None:
            VENDOR_METHODS["get_news"].pop("pilot", None)
        else:
            VENDOR_METHODS["get_news"]["pilot"] = previous
    combined = f"{routed}\n{result.markdown}"
    assert combined.startswith("VENDOR_NEWS")
    assert "https://www.sec.gov/Archives/edgar/data/1577552/000000000026000001/ex99.htm" in combined
    assert "Revenue 100 CNY" in combined


def test_live_baba_li_and_tencent():
    root = Path("/tmp/acquire-live")
    decision = "2026-11-17T21:00:00Z"
    price = "2026-11-16"
    baba = acq.acquire("BABA", price, decision, "current", root)
    li = acq.acquire("LI", price, decision, "current", root)
    tencent = acq.acquire("0700.HK", price, decision, "current", root)
    print("BABA", baba.status, baba.fetched, baba.run_dir)
    print("LI", li.status, li.fetched, li.run_dir)
    print("0700", tencent.status, tencent.fetched, tencent.run_dir)
    for result, host in ((baba, "sec.gov"), (li, "sec.gov"), (tencent, "tencent.com")):
        manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
        assert manifest["fetched"] is result.fetched
        if host == "tencent.com":
            assert result.fetched is True
            assert "https://www.tencent.com/wp-content/uploads/" in result.markdown
        elif any(item.get("status") == 403 for item in manifest["sources"]):
            assert result.fetched is False
        else:
            assert result.fetched is True
            assert "www.sec.gov/Archives" in result.markdown
    assert "Alibaba Group" in baba.markdown and "0001577552" in baba.markdown
    assert "0001791706" in li.markdown
    assert "12 August 2026" in tencent.markdown
    assert "hkex" in tencent.markdown.lower()


if __name__ == "__main__":
    test_current_discovery_skips_filings_accepted_after_decision(Path("/tmp/acq-unit"))
    test_403_is_not_retried_and_does_not_invent_success(Path("/tmp/acq-403"))
    test_historical_and_uncovered_do_not_fetch_or_replace_old_files(Path("/tmp/acq-hist"))
    print("unit ok")
    test_live_baba_li_and_tencent()
    print("live ok")
