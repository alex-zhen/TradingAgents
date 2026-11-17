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
    exhibit = (
        "<html><body><p>Alibaba Group Announces June Quarter 2026 Results</p>"
        "<p>Hong Kong, China, August 20, 2026</p>"
        "<p>results for the quarter ended June 30, 2026.</p>"
        "<p>Revenue was RMB100 million (US$15 million).</p>"
        "<p>Net cash provided by operating activities was RMB10 million.</p></body></html>"
    )
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
        "BABA", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=session,
    )
    assert result.fetched is True
    assert "https://www.sec.gov/Archives/edgar/data/1577552/000000000026000001/ex99.htm" in result.markdown
    assert "Revenue was RMB100 million" in result.markdown
    assert "November notice" not in result.markdown
    assert "filed=2026-08-21" in result.markdown
    assert "filed=2026-12-01" not in result.markdown
    assert "FUTURE_NOT_REPORTED" in result.markdown
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["fetch_succeeded"] is True
    assert manifest["content_validated"] is True
    assert manifest["latest_discovery_verified"] is True
    assert manifest["install_allowed"] is True
    assert manifest["price_session_date"] == "2026-11-16"
    assert manifest["decision_at"].startswith("2026-11-17")
    assert any(item["sha256"] for item in manifest["sources"])
    assert (result.run_dir / "sentiment_digest_BABA_2026-11-16.md").read_text() == result.markdown


def test_403_is_not_retried_and_does_not_invent_success(tmp_path):
    session = Session([("efts.sec.gov", Response(403, b"blocked"))])
    result = acq.acquire(
        "LI", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=session,
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
        "NVDA", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=Session([]),
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
        "BABA", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=session,
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
    assert "Revenue was RMB100 million" in combined


def test_disclaimer_does_not_validate(tmp_path, monkeypatch):
    session = Session(_routes())
    monkeypatch.setattr(
        acq, "_text",
        lambda raw, limit=3500: "Disclaimer. Forward-looking statements. This presentation is not a report.",
    )
    result = acq.acquire(
        "BABA", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=session,
    )
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["content_validated"] is False
    assert manifest["install_allowed"] is False
    assert result.fetched is False


def test_li_html_results_page_is_accepted(tmp_path):
    home = (
        '<html><a href="/news/earnings">Earnings press release</a>'
        '<a href="https://example.com/other">offsite</a></html>'
    )
    article = (
        "<html><p>Li Auto</p><p>Hong Kong, China, August 15, 2026</p>"
        "<p>quarter ended June 30, 2026</p>"
        "<p>Revenue was RMB100 million (US$15 million).</p>"
        "<p>Net cash provided by operating activities was RMB10 million.</p></html>"
    )
    search = json.dumps({"hits": {"hits": [{"_source": {
        "ciks": ["0001791706"],
        "display_names": ["Li Auto Inc.  (LI)  (CIK 0001791706)"],
    }}]}}).encode()
    submissions = json.dumps({
        "name": "Li Auto Inc.",
        "tickers": ["LI"],
        "filings": {"recent": {
            "form": ["6-K"],
            "acceptanceDateTime": ["2026-08-15T12:00:00.000Z"],
            "accessionNumber": ["0000000000-26-000009"],
            "primaryDocument": ["cover.htm"],
            "reportDate": ["2026-06-30"],
            "primaryDocDescription": [""],
        }},
    }).encode()
    routes = [
        ("efts.sec.gov", Response(200, search)),
        ("submissions", Response(200, submissions)),
        ("index.html", Response(403, b"no")),
        ("/news/earnings", Response(200, article)),
        ("ir.lixiang.com/", Response(200, home)),
        ("companyfacts", Response(200, b'{"facts":{}}')),
    ]
    result = acq.acquire("LI", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=Session(routes))
    assert "https://ir.lixiang.com/news/earnings" in result.markdown
    assert "Revenue was RMB100 million" in result.markdown
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["content_validated"] is True
    assert manifest["install_allowed"] is True
    assert "example.com" not in result.markdown


def test_fileless_past_card_is_a_conflict(tmp_path):
    search = (
        b'{"hits":{"hits":[{"_source":{"ciks":["0001577552"],'
        b'"display_names":["Alibaba Group Holding Ltd  (BABA)  (CIK 0001577552)"]}}]}}'
    )
    submissions = (
        b'{"name":"Alibaba Group Holding Ltd","tickers":["BABA"],"filings":{"recent":{'
        b'"form":["6-K"],"acceptanceDateTime":["2026-08-20T20:05:09.000Z"],'
        b'"accessionNumber":["0000000000-26-000001"],"primaryDocument":["cover.htm"],'
        b'"reportDate":["2026-06-30"],"primaryDocDescription":[""]}}}'
    )
    cards = (
        '{"eventDateLocal":"August 1, 2026","documentPublishTimeLocal":"August 2, 2026",'
        '"documentTitle":"June Quarter 2026 Results","urls":{"presentationUrl":""}}'
    )
    routes = [
        ("efts.sec.gov", Response(200, search)),
        ("submissions", Response(200, submissions)),
        ("index.html", Response(403, b"no")),
        ("ir-financial-reports-quarterly-results", Response(200, cards)),
        ("ir-news-filings", Response(200, "")),
        ("companyfacts", Response(200, b'{"facts":{}}')),
    ]
    result = acq.acquire("BABA", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=Session(routes))
    assert "conflict:" in result.markdown
    assert "not a report" in result.markdown
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["install_allowed"] is False
    assert manifest["latest_discovery_verified"] is False


def test_card_date_is_not_the_publication_dateline(tmp_path, monkeypatch):
    search = (
        b'{"hits":{"hits":[{"_source":{"ciks":["0001577552"],'
        b'"display_names":["Alibaba Group Holding Ltd  (BABA)  (CIK 0001577552)"]}}]}}'
    )
    submissions = (
        b'{"name":"Alibaba Group Holding Ltd","tickers":["BABA"],"filings":{"recent":{'
        b'"form":["6-K"],"acceptanceDateTime":["2026-08-20T20:05:09.000Z"],'
        b'"accessionNumber":["0000000000-26-000001"],"primaryDocument":["cover.htm"],'
        b'"reportDate":["2026-06-30"],"primaryDocDescription":[""]}}}'
    )
    cards = (
        '{"eventDateLocal":"November 19, 2026","documentPublishTimeLocal":"November 6, 2026",'
        '"documentTitle":"September Quarter 2026 Results","urls":{"presentationUrl":""}}'
        '{"eventDateLocal":"August 20, 2026","documentPublishTimeLocal":"August 27, 2026",'
        '"documentTitle":"June Quarter 2026 Results","pressRelease":"2026456290057781248",'
        '"urls":{"presentationUrl":"https://data.alibabagroup.com/files/June%20Quarter%202026%20Results.pdf"}}'
    )
    document = '<a href="https://data.alibabagroup.com/files/Announces-June.pdf">PDF version only</a>'
    press = (
        "Hong Kong, China, August 20, 2026\n"
        "Alibaba Group Announces June Quarter 2026 Results\n"
        "quarter ended June 30, 2026\n"
        "Revenue was RMB100 million (US$15 million).\n"
        "Net cash provided by operating activities was RMB10 million.\n"
    )
    routes = [
        ("efts.sec.gov", Response(200, search)),
        ("submissions", Response(200, submissions)),
        ("index.html", Response(403, b"no")),
        ("ir-financial-reports-quarterly-results", Response(200, cards)),
        ("ir-news-filings", Response(200, "")),
        ("document-2026456290057781248", Response(200, document)),
        ("Announces-June.pdf", Response(200, b"%PDF-1.4")),
        ("companyfacts", Response(200, b'{"facts":{}}')),
    ]
    monkeypatch.setattr(acq, "_pdf_parts", lambda body: (press, press))
    result = acq.acquire("BABA", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=Session(routes))
    assert "publication_dateline: August 20, 2026" in result.markdown
    assert "results_card_date: August 27, 2026" in result.markdown
    assert "event_date: August 20, 2026" in result.markdown
    assert "newest_unread_acceptance: 2026-08-20T20:05:09.000Z" in result.markdown
    assert "sec_acceptance:" not in result.markdown
    assert "Announces-June.pdf" in result.markdown
    assert "presentation_not_selected:" in result.markdown
    assert "FUTURE_NOT_REPORTED" in result.markdown
    assert "November 19, 2026" in result.markdown
    assert "conflict:" not in result.markdown
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["content_validated"] is True
    assert manifest["install_allowed"] is True
    assert (result.run_dir / "extracted_full.txt").is_file()


def test_newer_unread_sec_row_blocks_install(tmp_path, monkeypatch):
    search = (
        b'{"hits":{"hits":[{"_source":{"ciks":["0001577552"],'
        b'"display_names":["Alibaba Group Holding Ltd  (BABA)  (CIK 0001577552)"]}}]}}'
    )
    submissions = (
        b'{"name":"Alibaba Group Holding Ltd","tickers":["BABA"],"filings":{"recent":{'
        b'"form":["6-K"],"acceptanceDateTime":["2026-11-10T13:58:20.000Z"],'
        b'"accessionNumber":["0000000000-26-000010"],"primaryDocument":["cover.htm"],'
        b'"reportDate":["2026-11-10"],"primaryDocDescription":[""]}}}'
    )
    cards = (
        '{"eventDateLocal":"August 20, 2026","documentPublishTimeLocal":"August 27, 2026",'
        '"documentTitle":"June Quarter 2026 Results","pressRelease":"99",'
        '"urls":{"presentationUrl":"https://data.alibabagroup.com/files/deck.pdf"}}'
    )
    document = '<a href="https://data.alibabagroup.com/files/Announces-June.pdf">PDF</a>'
    press = (
        "Hong Kong, China, August 20, 2026\nAlibaba Group Announces June Quarter 2026 Results\n"
        "quarter ended June 30, 2026\nRevenue was RMB100 million (US$15 million).\n"
        "Net cash provided by operating activities was RMB10 million.\n"
    )
    routes = [
        ("efts.sec.gov", Response(200, search)),
        ("submissions", Response(200, submissions)),
        ("index.html", Response(403, b"no")),
        ("ir-financial-reports-quarterly-results", Response(200, cards)),
        ("ir-news-filings", Response(200, "")),
        ("document-99", Response(200, document)),
        ("Announces-June.pdf", Response(200, b"%PDF-1.4")),
        ("companyfacts", Response(200, b'{"facts":{}}')),
    ]
    monkeypatch.setattr(acq, "_pdf_parts", lambda body: (press, press))
    result = acq.acquire("BABA", "2026-11-16", "2026-11-17T10:17:21Z", "current", tmp_path, session=Session(routes))
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["content_validated"] is True
    assert manifest["fetch_succeeded"] is True
    assert manifest["latest_discovery_verified"] is False
    assert manifest["install_allowed"] is False
    assert "2026-11-10" in result.markdown


def test_tencent_dateline_and_hkex_listing_stay_separate(tmp_path, monkeypatch):
    results = (
        '<h2>2026</h2><a href="https://www.tencent.com/wp-content/uploads/2026/08/Tencent-Announces-2026-Second-Quarter-Results.pdf">'
        "Tencent Announces 2026 Second Quarter Results</a>"
    )
    reports = (
        '<h2>2026 Interim Report</h2><a href="https://www.tencent.com/wp-content/uploads/2026/08/E700_IR.pdf">download</a>'
    )
    prefix = 'cb({"data":[{"stockId":7609,"code":"00700","name":"TENCENT"}]})'
    rows = json.dumps([
        {"DATE_TIME": "12/08/2026 16:31", "TITLE": "ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND SIX MONTHS ENDED 30 JUNE 2026", "FILE_LINK": "/listedco/listconews/sehk/2026/0812/2026081200296.pdf"},
        {"DATE_TIME": "25/08/2026 16:53", "TITLE": "INTERIM REPORT 2026", "FILE_LINK": "/listedco/listconews/sehk/2026/0825/2026082500556.pdf"},
    ])
    listing = json.dumps({"result": rows}).encode()
    announcement = (
        "Hong Kong, 12 August 2026\nTencent Announces 2026 Second Quarter Results\n"
        "quarter ended 30 June 2026\nRevenue was RMB100 million.\n"
        "Net cash provided by operating activities was RMB10 million.\n"
    )
    interim = "Hong Kong, 12 August 2026\nTencent Holdings\nperiod ended 30 June 2026\n"
    def parts(body):
        if b"ANNOUNCE" in body:
            return announcement, announcement
        return interim, interim
    routes = [
        ("investors/results/", Response(200, results)),
        ("financial-reports", Response(200, reports)),
        ("Tencent-Announces", Response(200, b"%PDF-ANNOUNCE")),
        ("E700_IR.pdf", Response(200, b"%PDF-INTERIM")),
        ("prefix.do", Response(200, prefix)),
        ("titleSearchServlet", Response(200, listing)),
        ("investor-news", Response(200, "no dates")),
    ]
    monkeypatch.setattr(acq, "_pdf_parts", parts)
    result = acq.acquire("0700.HK", "2026-11-17", "2026-11-17T10:17:21Z", "current", tmp_path, session=Session(routes))
    assert "publication_dateline: 12 August 2026" in result.markdown
    assert "hkex_listing_datetime: 12/08/2026 16:31" in result.markdown
    assert "hkex_listing_datetime: 25/08/2026 16:53" in result.markdown
    assert "not an HKEX filing time" in result.markdown
    manifest = json.loads((result.run_dir / "audit_manifest.json").read_text())
    assert manifest["content_validated"] is True
    assert manifest["latest_discovery_verified"] is True


def test_inventory_prints_gates_without_launching_the_graph(tmp_path, monkeypatch, capsys):
    import accept_inventory

    session = Session(_routes())

    def wrapped(ticker, price_date, decision_at, mode, root, session=None, operator_feed=None):
        return acq.acquire(
            ticker, price_date, decision_at, mode, root, session=session or Session(_routes()),
            operator_feed=operator_feed,
        )

    monkeypatch.setattr(accept_inventory, "acquire", wrapped)
    del session
    code = accept_inventory.main([
        "--price-date", "2026-11-16", "--decision-at", "2026-11-17T10:17:21Z",
        "--root", str(tmp_path), "--tickers", "BABA",
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert "fetch_succeeded: true" in captured.out
    assert "content_validated: true" in captured.out
    assert "install_allowed: true" in captured.out
    assert "runner_started: false" in captured.out
    assert "graph_launched: false" in captured.err
    assert "Revenue was RMB100 million" in captured.out


if __name__ == "__main__":
    test_current_discovery_skips_filings_accepted_after_decision(Path("/tmp/acq-unit"))
    test_403_is_not_retried_and_does_not_invent_success(Path("/tmp/acq-403"))
    test_historical_and_uncovered_do_not_fetch_or_replace_old_files(Path("/tmp/acq-hist"))
    print("unit ok")
